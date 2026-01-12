
async def _delete_message_safe(message):
    try:
        if message:
            await message.delete()
    except Exception:
        return

import os
import logging
logger = logging.getLogger(__name__)
import time
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes


MAX_REQUESTS_PER_USER = 5
MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB = os.getenv("MONGO_DB", "keepalive").strip() or "keepalive"
REQUEST_LIMIT_WINDOW = 48 * 60 * 60  # 48 hours in seconds



# Extra admin/user features
COOLDOWN_SECONDS = 5 * 60  # 5 min
AUTO_CLOSE_WINDOW = 72 * 60 * 60  # 72 hours
AUTO_APPROVE_KEYWORDS = ["notes", "note", "pdf"]

REJECT_REASONS = [
    ("dup", "Already group me hai"),
    ("spell", "Spelling galat hai"),
    ("wrong", "Wrong / unclear request"),
    ("format", "Format sahi nahi"),
    ("notavail", "Abhi available nahi"),
    ("offtopic", "Off-topic request"),
]
# =========================
#  GLOBAL DB (shared)
# =========================
def _ensure_bot_data(context: ContextTypes.DEFAULT_TYPE):
    bd = context.application.bot_data

    # requests DB
    if "rq_db" not in bd:
        bd["rq_db"] = {"seq": {}, "items": {}}

    # language per user: "hx" (Hinglish) / "hi" (Hindi)
    if "rq_lang" not in bd:
        bd["rq_lang"] = {}

    # onboarding flag per user: True means user already got DM guide (and likely started bot)
    if "rq_onboarded" not in bd:
        bd["rq_onboarded"] = {}

    # cache bot username (for deep link)
    if "rq_bot_username" not in bd:
        bd["rq_bot_username"] = ""

    # blocked users
    if "rq_blocked" not in bd:
        bd["rq_blocked"] = set()

    # per-user cooldown last request timestamp
    if "rq_cooldown" not in bd:
        bd["rq_cooldown"] = {}

    # optional log channel/chat id
    if "rq_log_chat" not in bd:
        bd["rq_log_chat"] = None


def _rq_db(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    _ensure_bot_data(context)
    return context.application.bot_data["rq_db"]


def _lang_db(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    _ensure_bot_data(context)
    return context.application.bot_data["rq_lang"]


def _onboard_db(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    _ensure_bot_data(context)
    return context.application.bot_data["rq_onboarded"]


def _blocked_db(context: ContextTypes.DEFAULT_TYPE):
    _ensure_bot_data(context)
    return context.application.bot_data["rq_blocked"]

def _cooldown_db(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    _ensure_bot_data(context)
    return context.application.bot_data["rq_cooldown"]

def _log_chat_id(context: ContextTypes.DEFAULT_TYPE):
    _ensure_bot_data(context)
    return context.application.bot_data.get("rq_log_chat")

def _get_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    # default Hinglish
    return _lang_db(context).get(int(user_id), "hx")


def _set_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int, code: str):
    _lang_db(context)[int(user_id)] = code


def _is_onboarded(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return bool(_onboard_db(context).get(int(user_id), False))


def _set_onboarded(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    context.bot_data.setdefault("onboarded", {})[int(user_id)] = True


def _group_items(context: ContextTypes.DEFAULT_TYPE, group_id: int) -> List[Dict]:
    db = _rq_db(context)
    return db["items"].setdefault(group_id, [])


def _next_seq(context: ContextTypes.DEFAULT_TYPE, group_id: int) -> int:
    db = _rq_db(context)
    cur = int(db["seq"].get(group_id, 0)) + 1
    db["seq"][group_id] = cur
    return cur


def _find_request(context: ContextTypes.DEFAULT_TYPE, group_id: int, seq: int) -> Optional[Dict]:
    items = _group_items(context, group_id)
    for r in items:
        if int(r.get("seq", -1)) == int(seq):
            return r
    return None


def _norm(text: str) -> str:
    return " ".join((text or "").lower().strip().split())


def _bold(text: str) -> str:
    """Bold every non-empty line using Telegram Markdown."""
    text = text or ""
    lines = text.split("\n")
    out = []
    for line in lines:
        if line.strip():
            safe = line.replace("*", "\\*")
            out.append(f"*{safe}*")
        else:
            out.append("")
    return "\n".join(out)


def _is_blocked(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    bd = _blocked_db(context)
    try:
        return int(user_id) in set(map(int, bd))
    except Exception:
        return False

def _block_user(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    bd = _blocked_db(context)
    try:
        bd.add(int(user_id))
    except Exception:
        # if stored as list
        try:
            bd2 = set(bd)
            bd2.add(int(user_id))
            context.application.bot_data["rq_blocked"] = bd2
        except Exception:
            pass

def _cooldown_ok(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    now = int(time.time())
    cd = _cooldown_db(context)
    last = int(cd.get(int(user_id), 0))
    if now - last < COOLDOWN_SECONDS:
        return False
    cd[int(user_id)] = now
    return True

def _maybe_log(context: ContextTypes.DEFAULT_TYPE, text: str):
    chat_id = _log_chat_id(context)
    if not chat_id:
        return
    try:
        # fire and forget best-effort (async caller will await)
        return context.bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
    except Exception:
        return

def _auto_close_pending(context: ContextTypes.DEFAULT_TYPE):
    """Close pending requests older than AUTO_CLOSE_WINDOW."""
    db = _rq_db(context)
    now = int(time.time())
    changed = []
    for gid, items in (db.get("items") or {}).items():
        for r in items:
            if r.get("status") == "pending":
                created = int(r.get("created", 0))
                if now - created >= AUTO_CLOSE_WINDOW:
                    r["status"] = "rejected"
                    r["reason"] = "timeout"
                    r["handled_by"] = None
                    r["handled_at"] = now
                    changed.append(r)
    return changed


# =========================
#  MONGODB PERSISTENCE (onboarded / blocked / cooldown / 48h limit)
#  Works on Render FREE (no disk needed)
# =========================

_mongo_client = None
_mongo_db = None

def _mongo_enabled() -> bool:
    return bool(MONGO_URI)

def _mongo_get_db():
    global _mongo_client, _mongo_db
    if _mongo_db is not None:
        return _mongo_db
    if not _mongo_enabled():
        return None
    _mongo_client = AsyncIOMotorClient(MONGO_URI)
    _mongo_db = _mongo_client[MONGO_DB]
    return _mongo_db

async def _mongo_onboarded(user_id: int) -> bool:
    db = _mongo_get_db()
    if not db:
        return False
    doc = await db.onboarded.find_one({"_id": int(user_id)}, {"_id": 1})
    return doc is not None

async def _mongo_set_onboarded(user_id: int):
    db = _mongo_get_db()
    if not db:
        return
    await db.onboarded.update_one(
        {"_id": int(user_id)},
        {"$set": {"ts": int(time.time())}},
        upsert=True,
    )

async def _mongo_is_blocked(user_id: int) -> bool:
    db = _mongo_get_db()
    if not db:
        return False
    doc = await db.blocked.find_one({"_id": int(user_id)}, {"_id": 1})
    return doc is not None

async def _mongo_block(user_id: int):
    db = _mongo_get_db()
    if not db:
        return
    await db.blocked.update_one(
        {"_id": int(user_id)},
        {"$set": {"ts": int(time.time())}},
        upsert=True,
    )

async def _mongo_cooldown_can_send(user_id: int) -> bool:
    if COOLDOWN_SECONDS <= 0:
        return True
    db = _mongo_get_db()
    if not db:
        # fallback: allow if mongo not enabled
        return True
    doc = await db.cooldown.find_one({"_id": int(user_id)}, {"last_ts": 1})
    last = int(doc.get("last_ts", 0)) if doc else 0
    return (int(time.time()) - last) >= COOLDOWN_SECONDS

async def _mongo_cooldown_set(user_id: int):
    if COOLDOWN_SECONDS <= 0:
        return
    db = _mongo_get_db()
    if not db:
        return
    await db.cooldown.update_one(
        {"_id": int(user_id)},
        {"$set": {"last_ts": int(time.time())}},
        upsert=True,
    )

async def _mongo_limit_check_and_inc(user_id: int):
    """
    48h rolling window limit:
    returns (allowed, count_after)
    """
    db = _mongo_get_db()
    if not db:
        # fallback: allow if mongo not enabled
        return True, 1

    now = int(time.time())
    doc = await db.req_limit.find_one({"_id": int(user_id)}, {"window_start": 1, "count": 1})
    ws = int(doc.get("window_start", now)) if doc else now
    cnt = int(doc.get("count", 0)) if doc else 0

    if now - ws >= REQUEST_LIMIT_WINDOW:
        ws, cnt = now, 0

    if cnt >= MAX_REQUESTS_PER_USER:
        return False, cnt

    cnt2 = cnt + 1
    await db.req_limit.update_one(
        {"_id": int(user_id)},
        {"$set": {"window_start": ws, "count": cnt2}},
        upsert=True,
    )
    return True, cnt2


def _reason_label(code_: str) -> str:
    # used for reason display
    mapping = {
        "dup": "Already group me hai",
        "spell": "Spelling galat hai",
        "wrong": "Wrong / unclear request",
        "format": "Format sahi nahi",
        "notavail": "Abhi available nahi",
        "offtopic": "Off-topic request",
        "timeout": "Time out ho gaya",
    }
    return mapping.get(code_ or "", code_ or "")


def _user_request_count_48h(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> int:
    db = _rq_db(context)
    now = int(time.time())
    count = 0
    for _gid, items in db["items"].items():
        for r in items:
            if int(r.get("by_id", 0)) == int(user_id):
                created = int(r.get("created", 0))
                if now - created <= REQUEST_LIMIT_WINDOW:
                    count += 1
    return count


# =========================
#  TEXT (Hinglish + Hindi)
# =========================
def _t(lang: str, key: str, **kw) -> str:
    lang = lang if lang in ("hx", "hi") else "hx"

    T = {
        "lang_help": {
            "hx": "Language set karne ke liye:\n/lang hx  (Hinglish)\n/lang hi  (Hindi)",
            "hi": "Language set karne ke liye:\n/lang hx  (Hinglish)\n/lang hi  (Hindi)",
        },
        "lang_set_hx": {
            "hx": "✅ Language Hinglish set ho gayi.",
            "hi": "✅ Language Hinglish set ho gayi.",
        },
        "lang_set_hi": {
            "hx": "✅ Language Hindi set ho gayi.",
            "hi": "✅ Language Hindi set ho gayi.",
        },

        "pm_request_not_allowed": {
            "hx": (
                "📌 How it works\n\n"
                "👥 Group me request bhejo\n"
                "➡️ /request <item>\n"
                "   Example: /request Avengers\n\n"
                "📬 Status dekhna ho\n"
                "➡️ PM me /myrequests use karo"
            ),
            "hi": (
                "📌 How it works\n\n"
                "👥 Group me request bhejo\n"
                "➡️ /request <item>\n"
                "   Example: /request Avengers\n\n"
                "📬 Status dekhna ho\n"
                "➡️ PM me /myrequests use karo"
            ),
        },
        "usage_request": {
            "hx": "Use: /request <item>\nExample: /request React WKS",
            "hi": "Use: /request <item>\nExample: /request React WKS",
        },

        "check_dm_hint": {
            "hx": "📩 Check your DM\n\nPehle bot ko private chat me open karke /start karo,\nphir wapas group me aakar /request bhejna.",
            "hi": "📩 Check your DM\n\nPehle bot ko private chat me open karke /start karo,\nphir wapas group me aakar /request bhejna.",
        },
"dup_pending": {
            "hx": "📌 Same request already pending hai\nGroup: {group}\nID: #{id}\nItem: {item}\nStatus: pending\n\nStatus check: /myrequests",
            "hi": "📌 Same request pehle se pending hai\nGroup: {group}\nID: #{id}\nItem: {item}\nStatus: pending\n\nStatus check: /myrequests",
        },
        "submitted": {
            "hx": "✅ Request submit ho gaya\nGroup: {group}\nID: #{id}\nItem: {item}\nStatus: pending\n\nStatus check karne ke liye: /myrequests",
            "hi": "✅ Request submit ho gaya\nGroup: {group}\nID: #{id}\nItem: {item}\nStatus: pending\n\nStatus check karne ke liye: /myrequests",
        },
        "myreqs_empty": {
            "hx": "Koi request nahi mila.",
            "hi": "Koi request nahi mila.",
        },
        "myreqs_pm_only": {
            "hx": "Status dekhna ho toh bot PM me /myrequests use karo.",
            "hi": "Status dekhna ho toh bot PM me /myrequests use karo.",
        },
        "status_update": {
            "hx": "🔔 Request update\nGroup: {group}\nID: #{id}\nItem: {item}\nStatus: {status}",
            "hi": "🔔 Request update\nGroup: {group}\nID: #{id}\nItem: {item}\nStatus: {status}",
        },

        # /help full guide (PM)
        "help_full": {
            "hx": (
                "📌 Help (User)\n\n"
                "✅ /request <item>  (GROUP me)\n"
                "• Group me msg delete ho jayega\n"
                "• Bot DM me confirmation bhejega\n\n"
                "✅ /myrequests  (SIRF PM me)\n"
                "• Apni requests + status dekhne ke liye\n\n"
                "ℹ️ Pehli baar: bot ko PM me /start karna zaroori hai."
            ),
            "hi": (
                "📌 Help (User)\n\n"
                "✅ /request <item>  (GROUP me)\n"
                "• Group me msg delete ho jayega\n"
                "• Bot DM me confirmation bhejega\n\n"
                "✅ /myrequests  (SIRF PM me)\n"
                "• Apni requests + status dekhne ke liye\n\n"
                "ℹ️ Pehli baar: bot ko PM me /start karna zaroori hai."
            ),
        },
    }

    return T[key][lang].format(**kw)


# =========================
#  SAFE HELPERS
# =========================
async def _dm_safe(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str, reply_markup=None, *, bold: bool = True, parse_mode: str = "Markdown") -> bool:
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=_bold(text) if bold else text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode=parse_mode,
        )
        return True
    except (Forbidden, BadRequest):
        return False
    except Exception:
        return False


async def _delete_msg_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _is_admin_of_group(context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> bool:
    try:
        m = await context.bot.get_chat_member(group_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def _dm_all_admins(context: ContextTypes.DEFAULT_TYPE, group_id: int, text: str, reply_markup=None):
    try:
        admins = await context.bot.get_chat_administrators(group_id)
    except Exception:
        admins = []
    for a in admins:
        u = a.user
        if not u or u.is_bot:
            continue
        await _dm_safe(context, u.id, text, reply_markup=reply_markup, bold=False, parse_mode="Markdown")


async def _get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    bd = context.application.bot_data
    _ensure_bot_data(context)

    if bd.get("rq_bot_username"):
        return bd["rq_bot_username"]

    try:
        me = await context.bot.get_me()
        bd["rq_bot_username"] = me.username or ""
        return bd["rq_bot_username"]
    except Exception:
        bd["rq_bot_username"] = ""
        return ""


async def _send_group_hint(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """
    Group me short hint bhejne ke liye (only if DM fail).
    Note: auto-delete optional; agar job_queue nahi hai toh message reh jayega.
    """
    chat = update.effective_chat
    if not chat:
        return

    hint_msg = await context.bot.send_message(chat_id=chat.id, text=_bold(text), disable_web_page_preview=True, parse_mode="Markdown")

    # Optional auto-delete after 20s (only if job_queue exists)
    try:
        if getattr(context, "job_queue", None):
            async def _del(ctx: ContextTypes.DEFAULT_TYPE):
                try:
                    await ctx.bot.delete_message(chat_id=chat.id, message_id=hint_msg.message_id)
                except Exception:
                    pass

            context.job_queue.run_once(_del, when=5)
    except Exception:
        pass


# =========================
#  CALLBACK DATA + BUTTONS
# =========================
def _cb(action: str, group_id: int, seq: int) -> str:
    return f"rq|{action}|{group_id}|{seq}"


def _admin_buttons(group_id: int, seq: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=_cb("ok", group_id, seq)),
        InlineKeyboardButton("❌ Reject", callback_data=_cb("no", group_id, seq)),
    ]])

def _admin_buttons_with_reason(group_id: int, seq: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=_cb("ok", group_id, seq)),
        InlineKeyboardButton("❌ Reject", callback_data=_cb("no", group_id, seq)),
    ], [
        InlineKeyboardButton("📝 Reason", callback_data=_cb("r", group_id, seq)),
    ]])


def _reason_buttons(group_id: int, seq: int) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for code_, label in REJECT_REASONS:
        row.append(InlineKeyboardButton(label, callback_data=_cb(f"why:{code_}", group_id, seq)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=_cb("back", group_id, seq))])
    return InlineKeyboardMarkup(rows)


def _reason_label(code_: str) -> str:
    for c, label in REJECT_REASONS:
        if c == code_:
            return label
    return code_



# =========================
#  COMMANDS
# =========================
async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /lang hx  -> Hinglish
    /lang hi  -> Hindi
    Prefer PM, but group me bhi chalega (silent delete).
    """
    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    lang = _get_lang(context, user.id)

    # group me silent
    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)

    code = (context.args[0].strip().lower() if context.args else "")
    if code not in ("hx", "hi"):
        await _dm_safe(context, user.id, _t(lang, "lang_help"))
        return

    _set_lang(context, user.id, code)
    if code == "hx":
        await _dm_safe(context, user.id, _t(code, "lang_set_hx"))
    else:
        await _dm_safe(context, user.id, _t(code, "lang_set_hi"))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /help -> full guide (PM)
    Group me use hua toh delete + PM me bhej
    """
    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    lang = _get_lang(context, user.id)

    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)
        await _dm_safe(context, user.id, _t(lang, "help_full"))
        return

    await update.message.reply_text(_bold(_t(lang, "help_full")), parse_mode="Markdown")


async def cmd_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    GROUP only:
      - user: /request <item>
      - bot deletes message in group (silent)
      - first time: DM redirect + guide (no request created)
      - second time: request create + user/admin DM
    """
    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    lang = _get_lang(context, user.id)

    # PM me /request -> guide
    if chat.type == "private":
        await update.message.reply_text(_bold(_t(lang, "pm_request_not_allowed")), parse_mode="Markdown")
        return

    # group me user message delete (silent)
    await _delete_msg_safe(context, chat.id, update.message.message_id)

    # auto-close old pending (best-effort)
    _auto_close_pending(context)

    # blocked user check
    if (await _mongo_is_blocked(user.id)) if _mongo_enabled() else _is_blocked(context, user.id):
        await _dm_safe(context, user.id, "Aap blocked ho. Aap request nahi kar sakte.")
        return

    # cooldown check (spam control)
    if not (await _mongo_cooldown_can_send(user.id)) if _mongo_enabled() else _cooldown_ok(context, user.id):
        await _dm_safe(context, user.id, "5 min baad request bhejo.")
        return

    # 48h max request limit (MongoDB persistent)
    if _mongo_enabled():
        allowed, _cnt = await _mongo_limit_check_and_inc(user.id)
        if not allowed:
            await _dm_safe(context, user.id, "Aapki 48 hours ki request limit full ho gayi hai. 48 hours baad try karo.")
            return

    # short group reminder (auto-delete) to check DM
    mention = f"@{user.username}" if user.username else user.full_name
    await _send_group_hint(update, context, f"{mention}, " + _t(lang, "check_dm_hint"))

    # ---- First-time onboarding: DM guide first, request create nahi hogi ----
    if not (await _mongo_onboarded(user.id) if _mongo_enabled() else _is_onboarded(context, user.id)):
        ok = await _dm_safe(context, user.id, _t(lang, "first_time_dm"))
        if ok:
            # DM succeed => user can receive PM now, mark onboarded so next /request works
            _set_onboarded(context, user.id, True)
        else:
            # DM fail => user ne bot ko /start nahi kiya
            username = await _get_bot_username(context)
            link = f"https://t.me/{username}?start=setup" if username else "Bot PM open karke /start karo"
            mention = f"@{user.username}" if user.username else user.full_name
            await _send_group_hint(update, context, _t(lang, "group_hint_open_pm"))
        return

    # normal flow: create request
    item = " ".join(context.args).strip()
    if not item:
        await _dm_safe(context, user.id, _t(lang, "usage_request"))
        return

    group_id = chat.id
    group_title = getattr(chat, "title", "") or "Group"

    items = _group_items(context, group_id)
    key = _norm(item)

    # auto-approve rules
    if any(k in key for k in AUTO_APPROVE_KEYWORDS):
        seq = _next_seq(context, group_id)
        req = {
            "seq": seq,
            "group_id": group_id,
            "group_title": group_title,
            "item": item,
            "key": key,
            "by_id": user.id,
            "by_name": user.full_name,
            "status": "approved",
            "priority": "medium",
            "note": None,
            "created": int(time.time()),
            "handled_by": None,
            "handled_at": int(time.time()),
            "reason": "auto",
        }
        items.append(req)
        await _dm_safe(context, user.id, f"✅ Auto-approved\nID: #{seq}\nItem: {item}")
        # log
        try:
            await _maybe_log(context, f"[AUTO-APPROVED] #{seq} {item} | {user.full_name} ({user.id}) | {group_title}")
        except Exception:
            pass
        return

    # ---- 48 hour request limit check ----
    if _user_request_count_48h(context, user.id) >= MAX_REQUESTS_PER_USER:
        await _dm_safe(context, user.id, "Request limit khatam ho gayi hai")
        return

    # duplicate pending
    for r in items:
        if r.get("key") == key and r.get("status") == "pending":
            await _dm_safe(context, user.id, _t(lang, "dup_pending", group=group_title, id=r["seq"], item=r["item"]))
            return

    # create
    seq = _next_seq(context, group_id)
    req = {
        "seq": seq,
        "group_id": group_id,
        "group_title": group_title,
        "item": item,
        "key": key,
        "by_id": user.id,
        "by_name": user.full_name,
        "status": "pending",  # pending / approved / rejected
        "priority": "medium",
        "note": None,
        "reason": None,
        "created": int(time.time()),
        "handled_by": None,
        "handled_at": None,
    }
    items.append(req)

    # DM user
    await _dm_safe(context, user.id, _t(lang, "submitted", group=group_title, id=seq, item=item))

    # DM admins (card + buttons)
    admin_text = (
        f"📌 New Request\n"
        f"Group: {group_title}\n"
        f"ID: #{seq}\n"
        f"Item: {item}\n"
        f"By: [{user.full_name}](tg://user?id={user.id}) (id {user.id})\n"
        f"Status: pending"
    )
    await _dm_all_admins(context, group_id, admin_text, reply_markup=_admin_buttons_with_reason(group_id, seq))
    if _mongo_enabled():
        await _mongo_cooldown_set(user.id)


async def cmd_myrequests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    PM ONLY:
      - /myrequests => list
    Group me => delete + DM hint
    """
    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    lang = _get_lang(context, user.id)

    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)
        await _dm_safe(context, user.id, _t(lang, "myreqs_pm_only"))
        return

    db = _rq_db(context)
    all_groups = db["items"]

    mine: List[Dict] = []
    for _gid, items in all_groups.items():
        for r in items:
            if int(r.get("by_id", 0)) == user.id:
                mine.append(r)

    if not mine:
        await update.message.reply_text(_bold(_t(lang, "myreqs_empty")), parse_mode="Markdown")
        return

    mine.sort(key=lambda r: int(r.get("created", 0)), reverse=True)
    mine = mine[:25]

    lines = []
    for r in mine:
        lines.append(
            f"#{r['seq']} — {r.get('item')}\n"
            f"Group: {r.get('group_title')}\n"
            f"Status: {r.get('status')}\n"
            f"—"
        )

    await update.message.reply_text(_bold("\n".join(lines)), parse_mode="Markdown")




async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int):
    """
    /pending (Admin):
      - Group/PM: pending requests list (cards) DM me bhejta hai.
      - Admin ko sab groups ki pending requests dikhengi.
    """
    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    lang = _get_lang(context, user.id)

    db = _rq_db(context)
    group_ids = list((db.get("items") or {}).keys())

    # Must be admin of at least one group (to reduce abuse)
    allowed = False
    for gid in group_ids[:50]:
        if await _is_admin_of_group(context, gid, user.id):
            allowed = True
            break
    if not allowed:
        # silent ignore in group, simple message in PM
        if chat.type == "private":
            await update.message.reply_text("No pending requests.")
        return

    # keep group clean
    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)

    # Collect pending requests across all groups (newest first)
    pending = []
    for gid in group_ids:
        items = (db.get("items") or {}).get(gid, []) or []
        for r in items:
            if r.get("status") == "pending":
                pending.append(r)
    pending.sort(key=lambda rr: int(rr.get("created", 0)), reverse=True)

    if not pending:
        # DM simple
        ok = await _dm_safe(context, user.id, "No pending requests.")
        if (not ok) and chat.type != "private":
            username = await _get_bot_username(context)
            link = f"https://t.me/{username}?start=setup" if username else "Bot PM open karke /start karo"
            mention = f"@{user.username}" if user.username else user.full_name
            await _send_group_hint(update, context, _t(lang, "group_hint_open_pm"))
        return

    # Send up to 20 cards in DM
    for r in pending[:20]:
        msg = (
            f"#{r.get('seq')} — {r.get('item')}\n"
            f"Group: {r.get('group_title')}\n"
            f"By: [{r.get('by_name')}](tg://user?id={r.get('by_id')})\n"
            f"Status: pending"
        )
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=msg,
                reply_markup=_admin_buttons_with_reason(int(r.get("group_id")), int(r.get("seq"))),
                disable_web_page_preview=True,
                parse_mode="Markdown",
            )
        except Exception:
            # If DM fails mid-way, stop and hint in group
            if chat.type != "private":
                username = await _get_bot_username(context)
                link = f"https://t.me/{username}?start=setup" if username else "Bot PM open karke /start karo"
                mention = f"@{user.username}" if user.username else user.full_name
                await _send_group_hint(update, context, _t(lang, "group_hint_open_pm"))
            break




async def cmd_editrequest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /editrequest <id> <new text>   (PM only)
    Only if your request is still pending.
    """
    if not update.message:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)
        await _dm_safe(context, user.id, "Edit karna ho toh PM me /editrequest use karo.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Use: /editrequest <id> <new text>")
        return

    try:
        seq = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid ID.")
        return

    new_text = " ".join(context.args[1:]).strip()
    if not new_text:
        await update.message.reply_text("New text missing.")
        return

    db = _rq_db(context)
    found = None
    for gid, items in (db.get("items") or {}).items():
        for r in items:
            if int(r.get("seq", -1)) == seq and int(r.get("by_id", 0)) == int(user.id):
                found = r
                break
        if found:
            break

    if not found:
        await update.message.reply_text("Request nahi mili.")
        return

    if found.get("status") != "pending":
        await update.message.reply_text("Ye request already handled hai.")
        return

    found["item"] = new_text
    found["key"] = _norm(new_text)

    await update.message.reply_text("✅ Updated. Admin ko update dikh jayega.")



async def cmd_setlog(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int):
    """
    /setlog <chat_id>  (Admin) - set log channel/chat id
    """
    if not update.message:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    # PM only
    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)
        return
    # must be admin of at least one group
    db = _rq_db(context)
    group_ids = list((db.get("items") or {}).keys())
    allowed = any([await _is_admin_of_group(context, gid, user.id) for gid in group_ids[:25]]) if group_ids else False
    if not allowed and user.id != owner_id:
        await update.message.reply_text("Not allowed.")
        return
    if not context.args:
        await update.message.reply_text("Use: /setlog <chat_id>")
        return
    try:
        cid = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid chat_id")
        return
    context.application.bot_data["rq_log_chat"] = cid
    await update.message.reply_text("✅ Log channel set.")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats (Admin) - show summary
    """
    if not update.message:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)
        await _dm_safe(context, user.id, "Stats dekhna ho toh PM me /stats use karo.")
        return

    db = _rq_db(context)
    group_ids = list((db.get("items") or {}).keys())
    allowed = any([await _is_admin_of_group(context, gid, user.id) for gid in group_ids[:25]]) if group_ids else False
    if not allowed:
        await update.message.reply_text("Not allowed.")
        return

    total = pending = approved = rejected = 0
    per_user = {}
    for gid, items in (db.get("items") or {}).items():
        for r in items:
            total += 1
            st = r.get("status")
            if st == "pending":
                pending += 1
            elif st == "approved":
                approved += 1
            elif st == "rejected":
                rejected += 1
            uid = int(r.get("by_id", 0))
            per_user[uid] = per_user.get(uid, 0) + 1

    top_uid = max(per_user, key=lambda k: per_user[k]) if per_user else None
    top_cnt = per_user.get(top_uid, 0) if top_uid else 0

    msg = (
        f"📊 Stats\\n\\n"
        f"Total: {total}\\n"
        f"Pending: {pending}\\n"
        f"Approved: {approved}\\n"
        f"Rejected: {rejected}\\n"
        f"Top requester: {top_uid} ({top_cnt})"
    )
    await update.message.reply_text(msg)

async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /note <id> <text> (Admin, PM)
    """
    if not update.message:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    if chat.type != "private":
        await _delete_msg_safe(context, chat.id, update.message.message_id)
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Use: /note <id> <text>")
        return
    try:
        seq = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid ID.")
        return
    text = " ".join(context.args[1:]).strip()

    db = _rq_db(context)
    found = None
    for gid, items in (db.get("items") or {}).items():
        for r in items:
            if int(r.get("seq", -1)) == seq:
                found = r
                break
        if found:
            break
    if not found:
        await update.message.reply_text("Request nahi mili.")
        return

    # must be admin of that group
    if not await _is_admin_of_group(context, int(found.get("group_id")), user.id):
        await update.message.reply_text("Not allowed.")
        return

    found["note"] = text
    await update.message.reply_text("✅ Note saved.")

async def cb_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int):
    """
    Admin buttons in DM:
      Approve / Reject
    """
    q = update.callback_query
    if not q:
        return
    await q.answer()

    data = q.data or ""
    parts = data.split("|")
    if len(parts) != 4 or parts[0] != "rq":
        return

    action = parts[1]  # ok / no
    group_id = int(parts[2])
    seq = int(parts[3])

    actor_id = q.from_user.id if q.from_user else 0

    # permission: owner OR group admin
    if actor_id != owner_id:
        if not await _is_admin_of_group(context, group_id, actor_id):
            return

    req = _find_request(context, group_id, seq)
    if not req:
        try:
            await q.edit_message_text("Request nahi mila / already clear.")
        except Exception:
            pass
        return


    if req.get("status") != "pending":
        try:
            await q.edit_message_text(f"Already handled ✅\nID #{seq} — {req.get('status')}")
        except Exception:
            pass
        return

    # Reason menu (no status change)
        if action == "r":
            try:
                await q.edit_message_text(
                    "Reason select karo:",
                    reply_markup=_reason_buttons(group_id, seq),
                )
            except Exception:
                pass
            return

        if action == "back":
            try:
                # rebuild the request card
                card = (
                    "📌 New Request\n"
                    f"Group: {req.get('group_title')}\n"
                    f"ID: #{seq}\n"
                    f"Item: {req.get('item')}\n"
                    f"By: {req.get('by_name')} ({req.get('by_id')})\n"
                    "Status: pending"
                )
                await q.edit_message_text(card, reply_markup=_admin_buttons_with_reason(group_id, seq))
            except Exception:
                pass
            return

        reject_reason = None
        if action.startswith("why:"):
            reject_reason = action.split(":", 1)[1].strip()

        if action == "ok":
            req["status"] = "approved"
        else:
            req["status"] = "rejected"
            if reject_reason:
                req["reason"] = reject_reason
    req["handled_by"] = actor_id
    req["handled_at"] = int(time.time())

    # notify requester in their language
    user_id = int(req.get("by_id"))
    user_lang = _get_lang(context, user_id)
    group_title = req.get("group_title", "Group")

    if not req.get("silent"):
        msg_text = _t(user_lang, "status_update", group=group_title, id=seq, item=req.get("item"), status=req.get("status"))
        if req.get("status") == "rejected" and req.get("reason"):
            msg_text += f"\nReason: {_reason_label(req.get('reason'))}"
        await _dm_safe(context, user_id, msg_text)

    # update admin message
    try:
        await q.edit_message_text(
            f"✅ Handled\n"
            f"Group: {group_title}\n"
            f"ID: #{seq}\n"
            f"Item: {req.get('item')}\n"
            f"By: {req.get('by_name')} ({req.get('by_id')})\n"
            f"Status: {req.get('status')}" + (f"\nReason: {_reason_label(req.get('reason'))}" if req.get("status")=="rejected" and req.get("reason") else "")
            )
    except Exception:
        pass


# =========================
#  REGISTER (main.py calls this)
# =========================
def register_request_system(application, *args):
    logger.info("Registering request system handlers...")
    """
    Compatible register:
      - old call: register_request_system(application, OWNER_ID)
      - your current main.py call: register_request_system(application, is_admin, OWNER_ID)
    Note: is_admin argument is ignored here; admin checks happen via Telegram get_chat_member.
    """
    # Accept both signatures. If called with (is_admin, owner_id) ignore is_admin.
    if len(args) == 1:
        owner_id = args[0]
    elif len(args) >= 2:
        owner_id = args[1]
    else:
        raise TypeError('register_request_system(application, OWNER_ID) expected')
    application.add_handler(CommandHandler("request", cmd_request))
    application.add_handler(CommandHandler("myrequests", cmd_myrequests))
    application.add_handler(CommandHandler("lang", cmd_lang))
    application.add_handler(CommandHandler("help", cmd_help))

    async def _pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await cmd_pending(update, context, owner_id)

    application.add_handler(CommandHandler("pending", _pending))

    async def _cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await cb_admin_action(update, context, owner_id)

    application.add_handler(CallbackQueryHandler(_cb, pattern=r"^rq\|"))
    logger.info("Request system handlers registered: /request, /pending, callbacks")
