import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes


def _norm(text: str) -> str:
    return " ".join((text or "").lower().strip().split())


def _queue(context: ContextTypes.DEFAULT_TYPE):
    return context.chat_data.setdefault("request_queue", [])


# /request <item>
async def cmd_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    item = " ".join(context.args).strip()
    if not item:
        await update.message.reply_text("Usage: /request <item>")
        return

    q = _queue(context)
    key = _norm(item)

    # Duplicate = upvote
    for i, r in enumerate(q):
        if r["key"] == key and r["status"] == "pending":
            voters = r.get("voters", [])
            if user.id in voters:
                await update.message.reply_text(
                    f"Already requested ✅\nPos: #{i+1}\n👍 {r.get('votes',0)}"
                )
                return

            voters.append(user.id)
            r["voters"] = voters
            r["votes"] = r.get("votes", 0) + 1
            q[i] = r
            context.chat_data["request_queue"] = q

            await update.message.reply_text(
                f"Upvoted 👍\nPos: #{i+1}\n👍 {r.get('votes',0)}"
            )
            return

    # New request
    req_id = f"{int(time.time())}_{user.id}"
    req = {
        "id": req_id,
        "item": item,
        "key": key,
        "by_id": user.id,
        "by_name": user.full_name,
        "status": "pending",
        "votes": 0,
        "voters": [],
        "created": int(time.time()),
        "msg_id": update.message.message_id,
    }
    q.append(req)
    context.chat_data["request_queue"] = q

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Upvote", callback_data=f"rq_up_{req_id}"),
        InlineKeyboardButton("✅ Approve", callback_data=f"rq_ok_{req_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"rq_no_{req_id}"),
    ]])

    await update.message.reply_text(
        f"📌 New Request\n"
        f"Item: {item}\n"
        f"By: {user.full_name}\n"
        f"Pos: #{len(q)}\n"
        f"👍 0",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# /myrequests
async def cmd_myrequests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    q = _queue(context)
    mine = [r for r in q if r["by_id"] == user.id]

    if not mine:
        await update.message.reply_text("No requests.")
        return

    text = "Your Requests:\n" + "\n".join(
        [f"- {r['item']} | {r['status']} | 👍{r.get('votes',0)}" for r in mine[-15:]]
    )
    await update.message.reply_text(text)


def register_request_system(application, is_admin_fn, owner_id: int):
    application.add_handler(CommandHandler("request", cmd_request))
    application.add_handler(CommandHandler("myrequests", cmd_myrequests))

    # /queue (admin)
    async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        uid = update.effective_user.id if update.effective_user else 0
        if not (uid == owner_id or await is_admin_fn(update, context)):
            await update.message.reply_text("Only admins allowed.")
            return

        q = _queue(context)
        pending = [r for r in q if r["status"] == "pending"]
        pending.sort(key=lambda r: (-r.get("votes",0), r.get("created",0)))

        if not pending:
            await update.message.reply_text("Queue empty.")
            return

        lines = ["🟡 Pending Requests (votes wise)"]
        for i, r in enumerate(pending[:30], start=1):
            lines.append(
                f"{i}. {r['item']} — {r['by_name']} — 👍{r.get('votes',0)}"
            )

        await update.message.reply_text("\n".join(lines))

    application.add_handler(CommandHandler("queue", cmd_queue))

    # Callbacks
    async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        if not q:
            return
        await q.answer()

        data = q.data or ""
        if not data.startswith("rq_"):
            return

        _, action, req_id = data.split("_", 2)
        items = _queue(context)

        target = None
        for r in items:
            if r["id"] == req_id:
                target = r
                break
        if not target:
            return

        # Upvote
        if action == "up":
            voters = target.get("voters", [])
            if q.from_user.id in voters:
                return
            voters.append(q.from_user.id)
            target["voters"] = voters
            target["votes"] = target.get("votes",0) + 1
            return

        # Approve / Reject (admin only)
        uid = q.from_user.id if q.from_user else 0
        if not (uid == owner_id or await is_admin_fn(update, context)):
            return

        target["status"] = "approved" if action == "ok" else "rejected"
        context.chat_data["request_queue"] = [r for r in items if r["id"] != req_id]

        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    application.add_handler(
        CallbackQueryHandler(cb, pattern=r"^rq_(up|ok|no)_")
    )
