import os
import logging
from dotenv import load_dotenv

load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from agents.db import init_db
from agents import logger
import agents.pa.agent as pa

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def _allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])


async def handle_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    try:
        n = int(context.args[0]) if context.args else 5
    except ValueError:
        await update.message.reply_text("Usage: /logs [number]")
        return
    runs = logger.get_recent_runs(n)
    if not runs:
        await update.message.reply_text("No runs logged yet.")
        return
    lines = []
    total_cost = 0.0
    for r in runs:
        cost = r.get("cost_usd") or 0.0
        total_cost += cost
        lines.append(f"• {r['agent']} [{r['status']}] — {r['task']} (${cost:.4f})")
    lines.append(f"\nTotal shown: ${total_cost:.4f}")
    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4093] + "..."
    await update.message.reply_text(text)


def main():
    init_db()
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("logs", handle_logs))
    pa.register_handlers(app)
    app.run_polling()


if __name__ == "__main__":
    main()
