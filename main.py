import os
import asyncio
import logging
import threading
import time
from request_queue import register_request_system
from http.server import BaseHTTPRequestHandler, HTTPServer
from random import choice
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ---------- LOGGING ----------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- CONFIG ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # your Telegram user id

DELETE_DELAY = int(os.getenv("DELETE_DELAY", "300"))
PORT = int(os.getenv("PORT", "10000"))  # for Render / Railway / UptimeRobot ping

PROMO_PATTERNS = [
    "t.me/",
    "telegram.me/",
    "discord.gg/",
    "chat.whatsapp.com/",
    "youtube.com/",
    "youtu.be/",
    "instagram.com/",
    "facebook.com/",
    "bit.ly/",
    "tinyurl.com/",
    "goo.gl/",
]

# Extended NSFW patterns


# Patterns that indicate users are trying to solicit direct/private messages.  These
# phrases are often used for self‑promotion in groups. When any of these
# substrings are detected in a message, the bot will remove the message
# automatically.  This feature extends the existing anti‑promotion logic
# without interfering with other functionality.
DM_PROMO_PATTERNS = [
    # English common phrases
    "dm me", "pm me", "dm karo", "pm karo",
    "private message", "private me", "private mai",
    "msg me", "message me", "inbox me",
    "dm mai de dunga", "pm mai de dunga",
    "contact me privately", "dm me for", "pm me for",
    # Hindi/Hinglish variations
    "dm karo", "dm kr", "pm karo", "pm kr",
    "dm me le", "pm me le", "private mai", "private me bhej",
]
NSFW_PATTERNS = [
    "porn", "pornhub", "xvideos", "xnxx", "xhamster", "redtube", "youporn", "brazzers", "bangbros",
    "hentai", "rule34", "xxx", "nsfw", "nude", "nudes", "nudity", "boobs", "tits",
    "pussy", "cock", "dick", "dildo", "vibrator", "cum", "cumshot", "creampie", "squirt",
    "squirting", "fuck", "fucking", "fucker", "asshole", "anal", "bj", "blowjob", "handjob",
    "deepthroat", "fingering", "69", "threesome", "orgy", "fetish", "pegging", "bdsm", "bondage",
    "camsex", "camgirl", "camsoda", "chaturbate", "onlyfans", "fansly", "escort", "callgirl",
    "sex", "sexchat", "sext", "sexting", "hotsex", "leakednudes", "leakednude", "sextape",
    "milf", "teenporn", "stepmom", "stepsis",

    # bypass / stylized
    "s3x", "pr0n", "p0rn", "n00ds", "lewd", "xnx", "fap", "fapping", "jerkoff",

    # hindi / hinglish
    "lund", "loda", "lauda", "gaand", "gand", "chut", "choot",
    "randi", "randiya", "chinal", "bhosdi", "bhosdike",
    "bhenchod", "behenchod", "madarchod", "mc ", " bc ", "lavde",
]

NSFW_EMOJI = ["🍆", "🍑", "💦", "👅", "🔞", "👙", "💋", "🤤"]

SAVAGE_COMMENTS = [
    "XP dekhke lagta hai tu kaafi time se active hai.",
    "Presence strong hai, group tere ko jaanta hai.",
    "Tu message nahi, poori vibe bhejta hai.",
    "Tere bina group chal toh jayega, par maza kam ho jayega.",
    "Consistency OP, aise hi chat garam rakh.",
]

RANK_TIERS = {
    0:    ["Dust Mode", "Background NPC", "Beginner Mode", "Silent Reader"],
    11:   ["Quiet Observer", "Human Buffering", "Slow Starter"],
    51:   ["Active Human Being", "Chat Me Entry Ho Gayi", "Warm-Up Member"],
    151:  ["Chat Enthusiast", "Daily Visitor", "Consistent Texter"],
    301:  ["Vibe Distributor", "Group Regular", "Core Member"],
    701:  ["Friendly Veteran", "Old Soul of Group", "Always-There Member"],
    1500: ["Community Legend", "Mythical OG", "Unskippable Member"],
}

ACHIEVEMENT_TIERS = [
    {
        "xp": 50,
        "title": "Active Human 💬",
        "messages": [
            "Ab group ne finally tujhe notice karna start kiya hai.",
            "Good! Ab tu sirf read-only member nahi raha.",
        ],
    },
    {
        "xp": 150,
        "title": "Chat Enthusiast 🎧",
        "messages": [
            "Chat me energy sahi aa rahi hai, aise hi reply karta reh.",
            "Tera notification rate high lag raha hai 😄",
        ],
    },
    {
        "xp": 300,
        "title": "Vibe Distributor ✨",
        "messages": [
            "Ab group ka mood tumhare messages se set hota hai.",
            "Silent chat ko bhi tu active bana deta hai.",
        ],
    },
    {
        "xp": 600,
        "title": "Friendly Regular ☕",
        "messages": [
            "Tumhare bina chat history adhuri lagti hai.",
            "Ab tumko dekh ke lagta hai permanent seat hai yaha.",
        ],
    },
    {
        "xp": 1000,
        "title": "Meme Specialist 🤣",
        "messages": [
            "Tumhare memes se log genuinely haste hain.",
            "Meme quality stable hai, supply continue rakho.",
        ],
    },
    {
        "xp": 2000,
        "title": "Group Pillar 🧱",
        "messages": [
            "Jab tum kam active hote ho, group ajeeb se quiet ho jata hai.",
            "Tumhare bina group thoda khaali khaali lagta hai.",
        ],
    },
    {
        "xp": 3500,
        "title": "Community Legend 🏅",
        "messages": [
            "Har purane member ko tumhara naam pata hota hai.",
            "Tum conversation ka hamesha hissa rahe ho.",
        ],
    },
    {
        "xp": 6000,
        "title": "Mythical OG 🐉",
        "messages": [
            "Koi nahi jaanta tum kab join huye, bas itna ke tum hamesha se yahi the.",
            "OG level reach kar liya, ye sirf time + patience se possible hai.",
        ],
    },
    {
        "xp": 10000,
        "title": "Immortal WiFi Ghost 👑",
        "messages": [
            "XP dekhke lagta hai tumhare aur group ke beech unlimited data ka contract hai.",
            "Tum chat ka permanent background process ho ab.",
        ],
    },
]

MYSTIC_QUOTES = [
    "Some doors don’t open when knocked — they open when you're meant to enter.",
    "People spend years searching for rooms like this.\nSome are simply allowed in.",
    "If you're here, there's a reason — even if you're not aware of it yet.",
    "Silence is not empty — it carries meaning for those who can hear it.",
    "Not everyone belongs everywhere — but you belong here.",
    "Those who understand subtlety never need explanations.",
    "You didn’t find this place — this place found you.",
    "True access isn’t requested — it’s recognized.",
    "Only a few reach this far — fewer stay.",
]

# kept but not used now (username-independent detection)
OTHER_BOT_USERNAMES = ["jwj_bot"]

# ---------- LOG STORAGE ----------
MAX_LOGS = 500
ARCHIVE_FILE = "archive_logs.txt"


def add_log(context: ContextTypes.DEFAULT_TYPE, log_text: str):
    logs = context.chat_data.get("logs", [])

    timestamp = datetime.now().strftime("%d-%m %H:%M")
    entry = f"[{timestamp}] {log_text}"
    logs.append(entry)

    while len(logs) > MAX_LOGS:
        archive_entry = logs.pop(0)
        try:
            with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
                f.write(archive_entry + "\n")
        except Exception:
            pass

    context.chat_data["logs"] = logs


# ---------- HTTP KEEPALIVE SERVER ----------

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Telegram auto-delete bot running.\n")

    def log_message(self, format, *args):
        return  # avoid console spam


def run_http_server():
    port = PORT
    with HTTPServer(("", port), HealthHandler) as httpd:
        logger.info(f"HTTP health server running on port {port}")
        httpd.serve_forever()


# ---------- HELPERS ----------

def _md_bold_to_html(text: str) -> str:
    """
    Convert simple **bold** or *bold* to HTML <b>bold</b>.
    Escapes HTML to avoid parsing issues/injection.
    """
    if text is None:
        return ""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<b>\1</b>", escaped)
    return escaped


async def delete_after(bot, chat_id: int, msg_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


async def reply_autodelete(message, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode="Markdown"):
    delay = context.chat_data.get("delay", DELETE_DELAY)
    sent = await message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
    )
    asyncio.create_task(delete_after(context.bot, sent.chat.id, sent.message_id, delay))
    return sent


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Group admin check only. Private chats always False."""
    user = update.effective_user
    chat = update.effective_chat
    if not chat or not user:
        return False

    if chat.type == "private":
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def get_random_rank(xp: int) -> str:
    level = max(k for k in RANK_TIERS.keys() if xp >= k)
    return choice(RANK_TIERS[level])


def get_random_comment() -> str:
    return choice(SAVAGE_COMMENTS)


# ---------- Auto Language + Auto Tone Not Found System ----------

NOT_FOUND_PHRASES_EN = [
    "No result found",
    "No match detected",
    "Nothing found",
    "No stored entry",
    "No available result",
    "No matching record",
]

NOT_FOUND_REASONS_EN = [
    "the spelling may slightly differ or the entry may not be in the database yet",
    "the name might be correct, but the file may not be added yet",
    "the spelling seems fine, but the content may not be indexed",
    "it might exist under a different naming format",
    "the entry may not have been uploaded yet",
    "it could be pending database update",
]

NOT_FOUND_PHRASES_HI = [
    "Koi result nahi mila",
    "Koi clear match detect nahi hua",
    "Kuch match nahi mila",
    "Database se koi entry nahi aayi",
    "Abhi tak koi proper record nahi mila",
]

NOT_FOUND_REASONS_HI = [
    "spelling thodi alag ho sakti hai ya entry abhi database me nahi hai",
    "naam sahi bhi ho sakta, bas file abhi add nahi hui",
    "spelling theek lag rahi, par content shayad index nahi hua",
    "shayad ye kisi aur naming format me ho",
    "entry abhi upload nahi hui hogi",
]


def detect_hinglish(text: str) -> bool:
    if not text:
        return False

    if any("\u0900" <= ch <= "\u097F" for ch in text):
        return True

    lower = text.lower()
    hindi_words = [
        "hai", "tha", "hun", "hoon", "kya", "ka ", "ki ", "ke ",
        "mujhe", "chahiye", "bhai", "yaar", "req", "de do",
        "hind", "dub", "print", "hindi", "link", "episode"
    ]
    return any(w in lower for w in hindi_words)


def generate_premium_line(text: str) -> str:
    if detect_hinglish(text):
        phrase = choice(NOT_FOUND_PHRASES_HI)
        reason = choice(NOT_FOUND_REASONS_HI)
        return f"⚠️ {phrase} — {reason}."
    else:
        phrase = choice(NOT_FOUND_PHRASES_EN)
        reason = choice(NOT_FOUND_REASONS_EN)
        return f"⚠️ {phrase} — maybe {reason}."


def get_not_found_response(context: ContextTypes.DEFAULT_TYPE, source_text: str) -> str:
    count = context.chat_data.get("nf_counter", 0)
    context.chat_data["nf_counter"] = count + 1

    if count < 2:
        return generate_premium_line(source_text or "")

    if detect_hinglish(source_text or ""):
        return "❌ Not found — spelling thodi different ho sakti hai ya entry database me nahi hai."
    else:
        return "❌ Not found — spelling or database may be the issue."


# ---------- "SEARCHING..." HANDLERS ----------

async def handle_searching_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return

    orig = msg.reply_to_message
    chat_id = msg.chat.id
    orig_text = (orig.text or orig.caption or "")

    pending = context.chat_data.setdefault("pending_searches", {})
    pending[msg.message_id] = {
        "orig_id": orig.message_id,
        "orig_chat_id": chat_id,
        "orig_text": orig_text,
        "answered": False,
        "started_at": time.time(),
    }
    context.chat_data["pending_searches"] = pending

    async def timeout_check(search_msg_id: int, request_text: str):
        word_count = len(request_text.split())
        base = 10

        if word_count >= 3:
            base += 3
        if any(word in request_text.lower() for word in ["season", "episode", "ep", "part"]):
            base += 3
        if len(request_text) > 30:
            base += 3

        wait_time = max(10, min(base, 22))
        await asyncio.sleep(wait_time)

        pend = context.chat_data.get("pending_searches", {})
        entry = pend.get(search_msg_id)
        if not entry or entry.get("answered"):
            return

        text = get_not_found_response(context, entry.get("orig_text", ""))

        try:
            delay = context.chat_data.get("delay", DELETE_DELAY)
            sent = await context.bot.send_message(
                chat_id=entry["orig_chat_id"],
                text=text,
                reply_to_message_id=entry["orig_id"],
            )
            asyncio.create_task(delete_after(context.bot, sent.chat.id, sent.message_id, delay))
        except Exception:
            pass

        entry["answered"] = True
        pend[search_msg_id] = entry
        context.chat_data["pending_searches"] = pend

    asyncio.create_task(timeout_check(msg.message_id, orig_text))


async def mark_search_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return

    reply_to_id = msg.reply_to_message.message_id
    pending = context.chat_data.get("pending_searches", {})
    if not pending:
        return

    if reply_to_id in pending:
        entry = pending[reply_to_id]
        entry["answered"] = True
        pending[reply_to_id] = entry
        context.chat_data["pending_searches"] = pending
        return

    for sid, entry in pending.items():
        if entry.get("orig_id") == reply_to_id:
            entry["answered"] = True
            pending[sid] = entry
            context.chat_data["pending_searches"] = pending
            return


# ---------- MAIN MESSAGE HANDLER ----------

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user

    if not msg or not user:
        return

    chat_id = msg.chat.id
    raw_text = (msg.text or msg.caption or "")
    text = raw_text.lower()

    clean = (
        text.replace(" ", "")
            .replace(".", "")
            .replace("*", "")
            .replace("_", "")
            .replace("-", "")
            .replace("•", "")
            .replace("/", "")
            .replace("\\", "")
            .replace("|", "")
            .replace("$", "s")
            .replace("5", "s")
            .replace("@", "a")
            .replace("4", "a")
            .replace("3", "e")
            .replace("1", "i")
            .replace("!", "i")
            .replace("0", "o")
            .replace("€", "e")
            .replace("🍆", "dick")
            .replace("🍑", "ass")
            .replace("💦", "cum")
    )

    # schedule auto delete for every message
    delay = context.chat_data.get("delay", DELETE_DELAY)
    asyncio.create_task(delete_after(context.bot, chat_id, msg.message_id, delay))
    add_log(context, f"AUTO_DELETE_SCHEDULE chat={chat_id} user={user.id} delay={delay}")

    # ----- ANY BOT HANDLING (username-independent) -----
    if user.is_bot:
        bot_text = (msg.text or msg.caption or "").lower()

        # Agar koi bot "search" type message bhej raha hai as a reply -> treat as searching
        if "search" in bot_text and msg.reply_to_message:
            await handle_searching_message(update, context)
        else:
            # baaki replies = result aya, mark as answered
            await mark_search_answer(update, context)
        return

    # --- Anti NSFW ---
    if context.chat_data.get("nsfw_enabled", True):
        if any(nw in clean for nw in NSFW_PATTERNS) or any(e in text for e in NSFW_EMOJI):
            add_log(context, f"NSFW_BLOCK user={user.id} name={user.full_name!r} text={raw_text!r}")
            try:
                warn = await msg.reply_text("🚫 NSFW content removed.", quote=False)
                await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
                asyncio.create_task(delete_after(context.bot, warn.chat.id, warn.message_id, 5))
            except Exception:
                pass
            return

    # --- Anti promo / links / @ spam ---
    promo_mentions_enabled = context.chat_data.get("promo_mentions", True)
    is_link = any(pat in text for pat in PROMO_PATTERNS)
    is_tag_spam = promo_mentions_enabled and "@" in text
    # Detect solicitations to direct message / private messaging
    is_dm_promo = any(pat in text for pat in DM_PROMO_PATTERNS)

    if is_link or is_tag_spam or is_dm_promo:
        # Log separately for DM promotion or general promotion.
        reason_tag = "DM_PROMO_BLOCK" if is_dm_promo and not (is_link or is_tag_spam) else "PROMO_BLOCK"
        add_log(context, f"{reason_tag} user={user.id} name={user.full_name!r} text={raw_text!r}")
        try:
            warn = await msg.reply_text("🚫 Promotion / spam removed.", quote=False)
            await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
            asyncio.create_task(delete_after(context.bot, warn.chat.id, warn.message_id, 5))
        except Exception:
            pass
        return

    # --- Keyword filters ---
    filters_map = context.chat_data.get("filters", {})
    for word, response in filters_map.items():
        if word and word.lower() in text:
            add_log(context, f"FILTER_MATCH user={user.id} keyword={word!r}")
            safe_html = _md_bold_to_html(response)
            await reply_autodelete(msg, context, safe_html, parse_mode="HTML")
            break

    # --- XP system + achievements ---
    xp_data = context.chat_data.get("xp", {})
    entry = xp_data.get(user.id, {"xp": 0, "name": user.full_name})

    prev_xp = entry["xp"]
    entry["xp"] = prev_xp + 1
    entry["name"] = user.full_name
    new_xp = entry["xp"]

    xp_data[user.id] = entry
    context.chat_data["xp"] = xp_data

    add_log(context, f"XP_GAIN user={user.id} xp={new_xp}")

    ach_data = context.chat_data.get("achievements", {})
    user_achs = ach_data.get(user.id, [])

    for ach in ACHIEVEMENT_TIERS:
        threshold = ach["xp"]
        if prev_xp < threshold <= new_xp and threshold not in user_achs:
            title = ach["title"]
            msg_text = choice(ach["messages"])
            text_ach = (
                "🎉 Achievement Unlocked!\n\n"
                f"🏆 {title}\n"
                f"⭐ XP: {new_xp}\n\n"
                f"{msg_text}"
            )
            add_log(context, f"ACHIEVEMENT user={user.id} title={title!r} xp={new_xp}")
            await reply_autodelete(msg, context, text_ach)

            user_achs.append(threshold)
            ach_data[user.id] = user_achs
            context.chat_data["achievements"] = ach_data
            break


# ---------- COMMANDS ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user

    in_private = chat.type == "private"

    is_owner = OWNER_ID != 0 and user.id == OWNER_ID
    is_group_admin = False
    if not in_private:
        is_group_admin = await is_admin(update, context)

    show_admin_view = False
    if is_owner:
        show_admin_view = True
    elif not in_private and is_group_admin:
        show_admin_view = True

    if show_admin_view:
        delay = context.chat_data.get("delay", DELETE_DELAY)
        promo_mentions_enabled = context.chat_data.get("promo_mentions", True)
        nsfw_enabled = context.chat_data.get("nsfw_enabled", True)

        text = (
            "🕶 **Control Room – Access Granted**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"⏳ Auto-delete: **{delay}s**\n"
            f"📛 Promo filter: **{'ON' if promo_mentions_enabled else 'OFF'}**\n"
            f"🔞 NSFW filter: **{'ON' if nsfw_enabled else 'OFF'}**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🛠 **Admin Console**\n"
            "• `/menu` – Quick panel\n"
            "• `/delay <sec>` – Delete timer\n"
            "• `/filter word -> reply` – Add auto reply\n"
            "• `/filterlist`, `/filterdel <word>`\n"
            "• `/promomentions on/off`\n"
            "• `/nsfw on/off/status`\n"
            "• `/rank`, `/top`\n"
            "• `/logs`, `/logsfull`, `/logsexport`\n"
            "• `/logsclear`, `/logswipe`\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "_Keep it clean. Keep it quiet._"
        )
        await reply_autodelete(update.message, context, text)
        return

    quote = choice(MYSTIC_QUOTES)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Ａｃｃｅｓｓ  Ｇｒａｎｔｅｄ", url="https://t.me/yourGroupLink")]
    ])

    text = (
        "✨ **ＰＲＩＶＡＴＥ  ＡＣＣＥＳＳ**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"“{quote}”\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "_Tap to continue._"
    )

    sent = await update.message.reply_text(text, reply_markup=keyboard)
    delay = context.chat_data.get("delay", DELETE_DELAY)
    asyncio.create_task(delete_after(context.bot, sent.chat.id, sent.message_id, delay))


async def cmd_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not (update.effective_user.id == OWNER_ID or await is_admin(update, context)):
        return await reply_autodelete(update.message, context, "Only admins allowed.")

    if not context.args:
        d = context.chat_data.get("delay", DELETE_DELAY)
        return await reply_autodelete(update.message, context, f"Current delay: {d}s")

    try:
        value = int(context.args[0])
        context.chat_data["delay"] = value
        add_log(context, f"CONFIG delay_set value={value}")
        await reply_autodelete(update.message, context, f"Delay updated to {value}s.")
    except ValueError:
        await reply_autodelete(update.message, context, "Invalid format. Example: /delay 30")


async def cmd_filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not (update.effective_user.id == OWNER_ID or await is_admin(update, context)):
        return await reply_autodelete(update.message, context, "Only admins allowed.")

    text = update.message.text
    if "->" not in text:
        return await reply_autodelete(update.message, context, "Format:\n/filter hello -> reply text", parse_mode=None)

    payload = text[len("/filter"):].strip()
    word, reply_text = map(str.strip, payload.split("->", 1))

    filters_map = context.chat_data.get("filters", {})
    filters_map[word.lower()] = reply_text
    context.chat_data["filters"] = filters_map

    add_log(context, f"FILTER_ADD word={word!r}")
    await reply_autodelete(update.message, context, f"Filter added: {word}", parse_mode=None)


async def cmd_filter_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not (update.effective_user.id == OWNER_ID or await is_admin(update, context)):
        return await reply_autodelete(update.message, context, "Only admins allowed.")

    if not context.args:
        return await reply_autodelete(update.message, context, "Usage: /filterdel <word>", parse_mode=None)

    word = context.args[0].lower()
    filters_map = context.chat_data.get("filters", {})

    if word in filters_map:
        del filters_map[word]
        context.chat_data["filters"] = filters_map
        add_log(context, f"FILTER_DEL word={word!r}")
        await reply_autodelete(update.message, context, f"Removed filter: {word}", parse_mode=None)
    else:
        await reply_autodelete(update.message, context, "Filter not found.", parse_mode=None)


async def cmd_filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    filters_map = context.chat_data.get("filters", {})
    if not filters_map:
        return await reply_autodelete(update.message, context, "No filters set.")

    lines = [f"{w} -> {r}" for w, r in filters_map.items()]
    await reply_autodelete(update.message, context, "Filters:\n" + "\n".join(lines), parse_mode=None)


async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    xp_data = context.chat_data.get("xp", {})
    entry = xp_data.get(user.id, {"xp": 0, "name": user.full_name})
    xp = entry["xp"]
    rank = get_random_rank(xp)
    comment = get_random_comment()

    styled_name = f"『 {user.full_name} 』"
    styled_rank = f"⟢ {rank} ⟣"
    styled_xp = f"{xp:,}".replace(",", " ")

    text = (
        "✨ **ＡＣＣＥＳＳ  ＰＲＯＦＩＬＥ**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🧿 **Identity:**   {styled_name}\n"
        f"📊 **Signal:**     {styled_xp} XP\n"
        f"🏷 **Tier:**       {styled_rank}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🖋 _Internal Remark:_\n“{comment}”"
    )

    await reply_autodelete(update.message, context, text)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    xp_data = context.chat_data.get("xp", {})
    if not xp_data:
        return await reply_autodelete(update.message, context, "Empty leaderboard.")

    ranked = sorted(xp_data.values(), key=lambda x: x["xp"], reverse=True)[:10]
    lines = [
        f"{i+1}. 『 {u['name']} 』 — {u['xp']} XP"
        for i, u in enumerate(ranked)
    ]
    await reply_autodelete(update.message, context, "✨ Leaderboard\n" + "\n".join(lines))


async def cmd_promomentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not (update.effective_user.id == OWNER_ID or await is_admin(update, context)):
        return await reply_autodelete(update.message, context, "Only admins allowed.")

    if not context.args or context.args[0].lower() not in ("on", "off"):
        return await reply_autodelete(update.message, context, "Usage: /promomentions on/off")

    state = context.args[0].lower() == "on"
    context.chat_data["promo_mentions"] = state
    add_log(context, f"CONFIG promo_mentions={state}")
    await reply_autodelete(update.message, context, f"Promo tag filter: {'ON' if state else 'OFF'}")


async def cmd_promostatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    state = context.chat_data.get("promo_mentions", True)
    await reply_autodelete(update.message, context, f"Promo tag filter: {'ON' if state else 'OFF'}")


async def cmd_nsfw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not (update.effective_user.id == OWNER_ID or await is_admin(update, context)):
        return await reply_autodelete(update.message, context, "Only admins allowed.")

    if not context.args or context.args[0].lower() not in ("on", "off", "status"):
        return await reply_autodelete(update.message, context, "Usage: /nsfw on | off | status")

    mode = context.args[0].lower()

    if mode == "status":
        current = context.chat_data.get("nsfw_enabled", True)
        return await reply_autodelete(update.message, context, f"NSFW Filter: {'ON' if current else 'OFF'}")

    if mode == "on":
        context.chat_data["nsfw_enabled"] = True
        add_log(context, "CONFIG nsfw_enabled=True")
        return await reply_autodelete(update.message, context, "NSFW filter activated.")

    if mode == "off":
        context.chat_data["nsfw_enabled"] = False
        add_log(context, "CONFIG nsfw_enabled=False")
        return await reply_autodelete(update.message, context, "NSFW filter disabled.")


# ---------- LOG COMMANDS ----------

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != OWNER_ID and not await is_admin(update, context):
        return await reply_autodelete(update.message, context, "Only admins can view logs.")

    logs = context.chat_data.get("logs", [])
    if not logs:
        return await reply_autodelete(update.message, context, "📭 No logs recorded.")

    preview = logs[-50:]
    formatted = "\n".join(preview)
    await reply_autodelete(update.message, context, f"📜 Latest Logs (50):\n\n{formatted}")


async def cmd_logs_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != OWNER_ID and not await is_admin(update, context):
        return await reply_autodelete(update.message, context, "Only admins can view logs.")

    logs = context.chat_data.get("logs", [])
    text = "\n".join(logs) if logs else "No logs."

    await update.message.reply_document(
        document=text.encode("utf-8"),
        filename="live_logs.txt",
    )


async def cmd_logs_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != OWNER_ID and not await is_admin(update, context):
        return await reply_autodelete(update.message, context, "Only admins can view logs.")

    if not os.path.exists(ARCHIVE_FILE):
        return await reply_autodelete(update.message, context, "📁 No archive file yet.")

    await update.message.reply_document(
        document=open(ARCHIVE_FILE, "rb"),
        filename=ARCHIVE_FILE,
    )


async def cmd_logs_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != OWNER_ID and not await is_admin(update, context):
        return await reply_autodelete(update.message, context, "Only admins allowed.")

    context.chat_data["logs"] = []
    await reply_autodelete(update.message, context, "🧹 Live logs cleared.")


async def cmd_logs_wipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != OWNER_ID and not await is_admin(update, context):
        return await reply_autodelete(update.message, context, "Only admins allowed.")

    context.chat_data["logs"] = []
    if os.path.exists(ARCHIVE_FILE):
        try:
            os.remove(ARCHIVE_FILE)
        except Exception:
            pass

    await reply_autodelete(update.message, context, "⚠ Full log history wiped.")


# ---------- BUTTON MENU ----------

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    keyboard = [
        [
            InlineKeyboardButton("Top Users", callback_data="menu_top"),
            InlineKeyboardButton("My Rank", callback_data="menu_rank"),
        ],
        [
            InlineKeyboardButton("Settings", callback_data="menu_settings"),
        ],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    msg = await update.message.reply_text("Menu:", reply_markup=markup)
    delay = context.chat_data.get("delay", DELETE_DELAY)
    asyncio.create_task(delete_after(context.bot, msg.chat.id, msg.message_id, delay))


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "menu_top":
        xp_data = context.chat_data.get("xp", {})
        if not xp_data:
            await reply_autodelete(query.message, context, "Empty leaderboard.")
        else:
            ranked = sorted(xp_data.values(), key=lambda x: x["xp"], reverse=True)[:10]
            lines = [f"{i+1}. {u['name']} — {u['xp']} XP" for i, u in enumerate(ranked)]
            await reply_autodelete(query.message, context, "Top Users:\n" + "\n".join(lines))

    elif data == "menu_rank":
        xp_data = context.chat_data.get("xp", {})
        entry = xp_data.get(user.id, {"xp": 0, "name": user.full_name})
        xp = entry["xp"]
        rank = get_random_rank(xp)
        comment = get_random_comment()
        text = (
            f"👤 {user.full_name}\n"
            f"XP: {xp}\n"
            f"Rank: {rank}\n\n"
            f"Status: {comment}"
        )
        await reply_autodelete(query.message, context, text)

    elif data == "menu_settings":
        delay = context.chat_data.get("delay", DELETE_DELAY)
        promo_state = "ON" if context.chat_data.get("promo_mentions", True) else "OFF"
        nsfw_state = "ON" if context.chat_data.get("nsfw_enabled", True) else "OFF"
        text = (
            "Settings:\n"
            f"- Auto-delete delay: {delay}s\n"
            f"- Promo tag filter: {promo_state}\n"
            f"- NSFW filter: {nsfw_state}"
        )
        await reply_autodelete(query.message, context, text)


# ---------- MAIN ----------

def build_application():
    """
    Build PTB Application and register all handlers.
    start_webhook.py can import this file and use `application`.
    """
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN env var not set.")
    # NOTE: Removed separate HTTP health server to avoid port conflict with Telegram webhook server on Render.

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_error_handler(on_error)

    # ✅ Request Queue system (approve/reject/pending/reasons/silent/block etc.)
    # IMPORTANT: signature is (application, owner_id)
    register_request_system(application, OWNER_ID)

    # Your existing bot commands/features
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("delay", cmd_delay))
    application.add_handler(CommandHandler("filter", cmd_filter_add))
    application.add_handler(CommandHandler("filterdel", cmd_filter_del))
    application.add_handler(CommandHandler("filterlist", cmd_filter_list))
    application.add_handler(CommandHandler("rank", cmd_rank))
    application.add_handler(CommandHandler("top", cmd_top))
    application.add_handler(CommandHandler("promomentions", cmd_promomentions))
    application.add_handler(CommandHandler("promostatus", cmd_promostatus))
    application.add_handler(CommandHandler("nsfw", cmd_nsfw))

    application.add_handler(CommandHandler("logs", cmd_logs))
    application.add_handler(CommandHandler("logsfull", cmd_logs_full))
    application.add_handler(CommandHandler("logsexport", cmd_logs_export))
    application.add_handler(CommandHandler("logsclear", cmd_logs_clear))
    application.add_handler(CommandHandler("logswipe", cmd_logs_wipe))

    application.add_handler(CallbackQueryHandler(cb_menu, pattern=r"^menu_"))

    # Message handler should stay last
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))

    logger.info("Application built successfully.")
    return application


# Expose for webhook runner (start_webhook.py does: import main as bot_main)
application = build_application()


async def on_error(update, context):
    logging.exception("Unhandled exception while handling an update:", exc_info=context.error)


def main():
    """
    Local/dev polling entrypoint.
    On Render webhook deployments, start_webhook.py will run the server and use `application`.
    """
    logger.info("Starting Telegram bot polling…")
    application.run_polling()


if __name__ == "__main__":
    main()
