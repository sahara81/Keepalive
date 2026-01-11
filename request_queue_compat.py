import time
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes


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


def _rq_db(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    _ensure_bot_data(context)
    return context.application.bot_data["rq_db"]


def _lang_db(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    _ensure_bot_data(context)
    return context.application.bot_data["rq_lang"]


def _onboard_db(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    _ensure_bot_data(context)
    return context.application.bot_data["rq_onboarded"]


def _get_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    # default Hinglish
    return _lang_db(context).get(int(user_id), "hx")


def _set_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int, code: str):
    _lang_db(context)[int(user_id)] = code


def _is_onboarded(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return bool(_onboard_db(context).get(int(user_id), False))


def _set_onboarded(context: ContextTypes.DEFAULT_TYPE, user_id: int, val: bool = True):
    _onboard_db(context)[int(user_id)] = val


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
            "hx": "Bhai /request group me karo.\nExample: /request React WKS\n\nStatus dekhna ho toh yahi PM me /myrequests use kar lena.",
            "hi": "Bhai /request group me karo.\nExample: /request React WKS\n\nStatus dekhna ho toh yahi PM me /myrequests use kar lena.",
        },
        "usage_request": {
            "hx": "Use: /request <item>\nExample: /request React WKS",
            "hi": "Use: /request <item>\nExample: /request React WKS",
        },

        # first-time DM guide (includes commands)
        "first_time_dm": {
            "hx": (
                "👋 Pehli baar setup!\n\n"
                "Bot ka system PM me chalta hai, group clean rahega.\n\n"
                "✅ Sabse pehle yahi PM me /start kar lo\n"
                "✅ Phir wapas group me jaake same /request dobara bhejna\n\n"
                "📌 Commands Guide:\n"
                "1) /request <item>  (GROUP me)\n"
                "   - Example: /request React WKS\n"
                "   - Group me message delete ho jayega\n"
                "   - Confirmation/status tumhe PM me aayega\n\n"
                "2) /myrequests  (SIRF PM me)\n"
                "   - Tumhari saari requests + status dikhata hai\n"
                "   - pending / approved(fulfilled) / rejected\n\n"
                "3) /help  (PM me)\n"
                "   - Same guide dubara dikhata hai\n\n"
                "4) /lang hx  (Hinglish)\n"
                "5) /lang hi  (Hindi)\n\n"
                "✅ Fulfilled kaise hota hai?\n"
                "- Admin approve karega → fulfilled (approved)\n"
                "- Admin reject karega → rejected\n"
                "- Dono case me tumhe PM me notification aayega\n\n"
                "Ab group me jaake apna /request dubara bhej do ✅"
            ),
            "hi": (
                "👋 Pehli baar setup!\n\n"
                "Bot ka system PM me chalta hai, group clean rahega.\n\n"
                "✅ Sabse pehle yahi PM me /start kar lo\n"
                "✅ Phir wapas group me jaake same /request dobara bhejna\n\n"
                "📌 Commands Guide:\n"
                "1) /request <item>  (GROUP me)\n"
                "   - Example: /request React WKS\n"
                "   - Group me message delete ho jayega\n"
                "   - Confirmation/status tumhe PM me aayega\n\n"
                "2) /myrequests  (SIRF PM me)\n"
                "   - Tumhari saari requests + status dikhata hai\n"
                "   - pending / approved(fulfilled) / rejected\n\n"
                "3) /help  (PM me)\n"
                "   - Same guide dubara dikhata hai\n\n"
                "4) /lang hx  (Hinglish)\n"
                "5) /lang hi  (Hindi)\n\n"
                "✅ Fulfilled kaise hota hai?\n"
                "- Admin approve karega → fulfilled (approved)\n"
                "- Admin reject karega → rejected\n"
                "- Dono case me tumhe PM me notification aayega\n\n"
                "Ab group me jaake apna /request dobara bhej do ✅"
            ),
        },

        "group_hint_open_pm": {
            "hx": "Pehle bot PM open karke /start karo, phir group me /request bhejna. Link: {link}",
            "hi": "Pehle bot PM open karke /start karo, phir group me /request bhejna. Link: {link}",
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
                "📘 BOT GUIDE / HELP\n\n"
                "🔹 Bot ka kaam:\n"
                "Ye bot group ko clean rakhta hai aur requests PM me handle karta hai.\n\n"
                "📌 Commands:\n\n"
                "1️⃣ /request <item>  (GROUP me)\n"
                "- Example: /request React WKS\n"
                "- Group me message delete ho jaata hai\n"
                "- Confirmation/status tumhe PM me aata hai\n\n"
                "2️⃣ /myrequests  (SIRF PM me)\n"
                "- Tumhari saari requests + status\n"
                "- pending / approved(fulfilled) / rejected\n\n"
                "3️⃣ /help  (PM me)\n"
                "- Ye guide dubara dikhata hai\n\n"
                "4️⃣ /lang hx  → Hinglish\n"
                "5️⃣ /lang hi  → Hindi\n\n"
                "🛠 Flow:\n"
                "- Tum /request bhejte ho\n"
                "- Admin approve → fulfilled\n"
                "- Admin reject → rejected\n"
                "- Har update ka PM notification\n\n"
                "ℹ️ Note:\n"
                "- Bot ko PM me /start karna zaroori hai (DM updates ke liye)\n"
            ),
            "hi": (
                "📘 BOT GUIDE / HELP\n\n"
                "🔹 Bot ka kaam:\n"
                "Ye bot group ko clean rakhta hai aur requests PM me handle karta hai.\n\n"
                "📌 Commands:\n\n"
                "1️⃣ /request <item>  (GROUP me)\n"
                "- Example: /request React WKS\n"
                "- Group me message delete ho jaata hai\n"
                "- Confirmation/status tumhe PM me aata hai\n\n"
                "2️⃣ /myrequests  (SIRF PM me)\n"
                "- Tumhari saari requests + status\n"
                "- pending / approved(fulfilled) / rejected\n\n"
                "3️⃣ /help  (PM me)\n"
                "- Ye guide dubara dikhata hai\n\n"
                "4️⃣ /lang hx  → Hinglish\n"
                "5️⃣ /lang hi  → Hindi\n\n"
                "🛠 Flow:\n"
                "- Tum /request bhejte ho\n"
                "- Admin approve → fulfilled\n"
                "- Admin reject → rejected\n"
                "- Har update ka PM notification\n\n"
                "ℹ️ Note:\n"
                "- Bot ko PM me /start karna zaroori hai (DM updates ke liye)\n"
            ),
        },
    }

    return T[key][lang].format(**kw)


# =========================
#  SAFE HELPERS
# =========================
async def _dm_safe(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str, reply_markup=None) -> bool:
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
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
        await _dm_safe(context, u.id, text, reply_markup=reply_markup)


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

    hint_msg = await context.bot.send_message(chat_id=chat.id, text=text, disable_web_page_preview=True)

    # Optional auto-delete after 20s (only if job_queue exists)
    try:
        if getattr(context, "job_queue", None):
            async def _del(ctx: ContextTypes.DEFAULT_TYPE):
                try:
                    await ctx.bot.delete_message(chat_id=chat.id, message_id=hint_msg.message_id)
                except Exception:
                    pass

            context.job_queue.run_once(_del, when=20)
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

    await update.message.reply_text(_t(lang, "help_full"))


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
        await update.message.reply_text(_t(lang, "pm_request_not_allowed"))
        return

    # group me user message delete (silent)
    await _delete_msg_safe(context, chat.id, update.message.message_id)

    # ---- First-time onboarding: DM guide first, request create nahi hogi ----
    if not _is_onboarded(context, user.id):
        ok = await _dm_safe(context, user.id, _t(lang, "first_time_dm"))
        if ok:
            # DM succeed => user can receive PM now, mark onboarded so next /request works
            _set_onboarded(context, user.id, True)
        else:
            # DM fail => user ne bot ko /start nahi kiya
            username = await _get_bot_username(context)
            link = f"https://t.me/{username}?start=setup" if username else "Bot PM open karke /start karo"
            mention = f"@{user.username}" if user.username else user.full_name
            await _send_group_hint(update, context, f"{mention}, " + _t(lang, "group_hint_open_pm", link=link))
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
        f"By: {user.full_name} (id {user.id})\n"
        f"Status: pending"
    )
    await _dm_all_admins(context, group_id, admin_text, reply_markup=_admin_buttons(group_id, seq))


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
        await update.message.reply_text(_t(lang, "myreqs_empty"))
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

    await update.message.reply_text("\n".join(lines))


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

    req["status"] = "approved" if action == "ok" else "rejected"
    req["handled_by"] = actor_id
    req["handled_at"] = int(time.time())

    # notify requester in their language
    user_id = int(req.get("by_id"))
    user_lang = _get_lang(context, user_id)
    group_title = req.get("group_title", "Group")

    await _dm_safe(
        context,
        user_id,
        _t(user_lang, "status_update", group=group_title, id=seq, item=req.get("item"), status=req.get("status"))
    )

    # update admin message
    try:
        await q.edit_message_text(
            f"✅ Handled\n"
            f"Group: {group_title}\n"
            f"ID: #{seq}\n"
            f"Item: {req.get('item')}\n"
            f"By: {req.get('by_name')} ({req.get('by_id')})\n"
            f"Status: {req.get('status')}"
        )
    except Exception:
        pass


# =========================
#  REGISTER (main.py calls this)
# =========================
def register_request_system(application, *args):
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

    async def _cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await cb_admin_action(update, context, owner_id)

    application.add_handler(CallbackQueryHandler(_cb, pattern=r"^rq\|(?:ok|no)\|"))
