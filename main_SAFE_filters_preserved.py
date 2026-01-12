from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram import Update
import logging

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ================= ERROR HANDLER =================
async def on_error(update: object, context):
    logging.error("Exception while handling an update:", exc_info=context.error)

# ================= FILTER SYSTEM (UNCHANGED) =================
FILTERS = {}

async def filter_add(update: Update, context):
    if len(context.args) < 2:
        return
    keyword = context.args[0].lower()
    reply = " ".join(context.args[1:])
    FILTERS[keyword] = reply
    await update.message.reply_text("Filter added ✅")

async def filter_delete(update: Update, context):
    if not context.args:
        return
    key = context.args[0].lower()
    FILTERS.pop(key, None)
    await update.message.reply_text("Filter removed ✅")

async def filter_watch(update: Update, context):
    text = update.message.text.lower()
    for key, reply in FILTERS.items():
        if key in text:
            await update.message.reply_text(reply)
            break

# ================= REQUEST SYSTEM =================
from request_queue_premium_message import register_request_system

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()

    # Request system (DM setup message)
    register_request_system(app)

    # Filter commands
    app.add_handler(CommandHandler("filter", filter_add))
    app.add_handler(CommandHandler("filterdel", filter_delete))

    # Filter watcher (THIS IS IMPORTANT)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_watch))

    # Error handler
    app.add_error_handler(on_error)

    app.run_polling()

if __name__ == "__main__":
    main()
