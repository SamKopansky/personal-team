import logging
import os
from typing import Any

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import agents.developer.agent as developer
import agents.manager.agent as manager
import agents.pa.agent as pa
from agents import logger, router
from agents.db import init_db

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

_log = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096

_AGENT_PREFIX = {
    "pa": "🟦 PA · ",
    "manager": "🟡 Manager · ",
    "researcher": "🔵 Researcher · ",
    "developer": "🟩 Developer · ",
}


def _allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])


def _truncate(text: str, prefix: str = "") -> str:
    max_len = TELEGRAM_MAX_LENGTH - len(prefix)
    if len(text) <= max_len:
        return prefix + text
    return prefix + text[: max_len - 3] + "..."


# ── /logs ─────────────────────────────────────────────────────────────────────


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
    if len(text) > TELEGRAM_MAX_LENGTH:
        text = text[: TELEGRAM_MAX_LENGTH - 3] + "..."
    await update.message.reply_text(text)


# ── Free-form routing ─────────────────────────────────────────────────────────


async def handle_freeform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route free-form messages through the Haiku router to the best agent."""
    if not _allowed(update):
        return
    import asyncio

    message = update.message.text
    chat_id = str(update.effective_chat.id)
    loop = asyncio.get_event_loop()

    decision = await loop.run_in_executor(None, router.route, message)
    agent = decision["agent"]
    confidence = decision["confidence"]

    if confidence < router.AUTO_ROUTE_THRESHOLD or agent == "clarify":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📋 Create ticket",
                        callback_data=f"route:manager:{message[:100]}",
                    ),
                    InlineKeyboardButton(
                        "🔍 Research this",
                        callback_data=f"route:researcher:{message[:100]}",
                    ),
                    InlineKeyboardButton(
                        "💬 Ask PA",
                        callback_data=f"route:pa:{message[:100]}",
                    ),
                ]
            ]
        )
        await update.message.reply_text(
            "Not sure how to handle this — did you mean:", reply_markup=keyboard
        )
        return

    await _dispatch(agent, message, chat_id, update)


async def _dispatch(agent: str, message: str, chat_id: str, update: Any):
    """Route a message to the chosen agent and send the reply."""
    import asyncio

    loop = asyncio.get_event_loop()

    # Researcher falls back to PA in Phase 1
    if agent == "manager":
        prefix = _AGENT_PREFIX["manager"]
        response = await loop.run_in_executor(None, manager.run, message, chat_id)
    elif agent == "researcher":
        prefix = _AGENT_PREFIX["pa"]  # PA fills in for Researcher until Phase 2
        response = await loop.run_in_executor(None, pa.run, message, chat_id)
    else:
        prefix = _AGENT_PREFIX["pa"]
        response = await loop.run_in_executor(None, pa.run, message, chat_id)

    try:
        await update.message.reply_text(_truncate(response, prefix), parse_mode="Markdown")
    except Exception as e:
        _log.error("Dispatch to %s failed: %s", agent, e, exc_info=True)
        await update.message.reply_text(f"{prefix}Something went wrong. Check /logs.")


# ── Inline button callbacks ───────────────────────────────────────────────────


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button taps from the clarification prompt."""
    if not _allowed(update):
        return
    import asyncio

    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if not data.startswith("route:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 3:
        return

    _, agent, message = parts
    chat_id = str(update.effective_chat.id)
    loop = asyncio.get_event_loop()

    await query.edit_message_text(f"Routing to {_AGENT_PREFIX.get(agent, agent).strip()} …")

    if agent == "manager":
        prefix = _AGENT_PREFIX["manager"]
        response = await loop.run_in_executor(None, manager.run, message, chat_id)
    else:
        # pa or researcher both go to PA in Phase 1
        prefix = _AGENT_PREFIX["pa"]
        response = await loop.run_in_executor(None, pa.run, message, chat_id)

    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_truncate(response, prefix),
            parse_mode="Markdown",
        )
    except Exception as e:
        _log.error("Callback routing failed: %s", e, exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{prefix}Something went wrong. Check /logs.",
        )


# ── App setup ─────────────────────────────────────────────────────────────────


def main():
    init_db()
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

    # Observability
    app.add_handler(CommandHandler("logs", handle_logs))

    # PA commands (/meal, /research, /clear)
    pa.register_handlers(app)

    # Manager commands (/status, /plan, /approve)
    manager.register_handlers(app)

    # Developer commands (/dev)
    developer.register_handlers(app)

    # Inline button callbacks (clarification flow)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Free-form message routing — must be registered last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_freeform))

    app.run_polling()


if __name__ == "__main__":
    main()
