"""Run the existing bot (main.py) using Telegram Webhooks instead of polling.

Why this file exists:
- Your current main.py builds the whole bot + handlers and finally calls application.run_polling().
- On Render free tier, polling tends to waste outbound traffic + can lead to instability.
- This runner monkey-patches python-telegram-bot's run_polling() to run_webhook() *without touching your existing bot logic*.

How to use on Render:
1) Add these Environment Variables in Render:
   - WEBHOOK_URL   = https://<your-service>.onrender.com
   - WEBHOOK_PATH  = <any-random-secret-path>  (example: hook_9f3a2c1e...)
   - BOT_TOKEN, OWNER_ID, DELETE_DELAY etc (already used by main.py)

2) Change your Start Command / Procfile to run:
   python start_webhook.py

Notes:
- This disables the extra HTTP keepalive server in main.py because webhook needs the same PORT.
- If you still want a /health endpoint for UptimeRobot, we can implement a small ASGI/Flask wrapper later.
"""

import os
import sys

# ---- Required env vars ----
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")   # e.g. https://your-app.onrender.com
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "").lstrip("/") # e.g. hook_abc123

if not WEBHOOK_URL or not WEBHOOK_PATH:
    raise SystemExit(
        "Missing WEBHOOK_URL / WEBHOOK_PATH env vars.\n"
        "Example:\n"
        "  WEBHOOK_URL=https://<your-service>.onrender.com\n"
        "  WEBHOOK_PATH=hook_<random>\n"
    )

WEBHOOK_FULL_URL = f"{WEBHOOK_URL}/{WEBHOOK_PATH}"

# Import telegram types AFTER env checks (helps fail fast in logs)
from telegram.ext import Application  # python-telegram-bot

# Monkey-patch run_polling -> run_webhook
_original_run_polling = Application.run_polling

def _run_webhook_instead(self: Application, *args, **kwargs):
    # Render provides PORT in env; main.py already reads it, but we also read it here.
    port = int(os.getenv("PORT", "10000"))
    return self.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_FULL_URL,
        drop_pending_updates=True,  # optional: prevents backlog on redeploy
    )

Application.run_polling = _run_webhook_instead  # type: ignore[attr-defined]

# Now import your existing bot code (keeps all features/handlers)
import main as bot_main  # noqa: E402

# Disable the separate keepalive HTTP server in main.py to avoid PORT conflict
if hasattr(bot_main, "run_http_server"):
    bot_main.run_http_server = lambda: None  # type: ignore[assignment]

if __name__ == "__main__":
    try:
        # Call your existing entrypoint; it will internally call application.run_polling(),
        # but due to the monkey-patch, it will actually start webhook mode.
        bot_main.main()
    finally:
        # Restore original method in case anything else imports this module
        Application.run_polling = _original_run_polling  # type: ignore[attr-defined]
