import datetime
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from agents import claude_client, context_manager, drive_client, logger
from agents.db import get_connection

MODEL = "claude-haiku-4-5"
SYSTEM_PROMPT_PATH = Path(__file__).parent / "system-prompt.md"

POSITIVE_SIGNALS = [
    "loved", "was a hit", "favorite", "he liked", "she liked",
    "liked it", "enjoyed", "great recipe", "make again",
]
NEGATIVE_SIGNALS = [
    "didn't like", "won't eat", "wouldn't eat", "avoid",
    "hated", "didn't eat", "refused",
]

TELEGRAM_MAX_LENGTH = 4096
MEMORY_SUMMARY_MAX_CHARS = 2000


def _truncate_for_telegram(text: str, prefix: str = "") -> str:
    max_len = TELEGRAM_MAX_LENGTH - len(prefix)
    if len(text) <= max_len:
        return prefix + text
    return prefix + text[: max_len - 3] + "..."


def detect_signals(message: str) -> tuple[bool, bool]:
    """Returns (has_positive, has_negative). Pure function — no side effects."""
    lower = message.lower()
    has_positive = any(s in lower for s in POSITIVE_SIGNALS)
    has_negative = any(s in lower for s in NEGATIVE_SIGNALS)
    return has_positive, has_negative


def _load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text()


def _get_settings() -> dict:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


def _get_favorites() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT recipe_name FROM favorites ORDER BY added_at DESC"
        ).fetchall()
        return [r["recipe_name"] for r in rows]
    finally:
        conn.close()


def _get_disliked() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT recipe_name FROM disliked ORDER BY added_at DESC"
        ).fetchall()
        return [r["recipe_name"] for r in rows]
    finally:
        conn.close()


def _get_recent_meal_plans(weeks: int = 4) -> list[str]:
    since = int(time.time()) - (weeks * 7 * 24 * 60 * 60)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT output FROM runs WHERE agent = 'pa' AND task = 'meal_plan' "
            "AND triggered_at > ? ORDER BY triggered_at DESC",
            (since,),
        ).fetchall()
        result = []
        for r in rows:
            if r["output"]:
                try:
                    result.append(json.loads(r["output"]))
                except (json.JSONDecodeError, TypeError):
                    result.append(r["output"])
        return result
    finally:
        conn.close()


def _extract_recipe_name(message: str, signal_type: str) -> str | None:
    prompt = (
        f"The user said: '{message}'\n\n"
        f"They expressed {'positive' if signal_type == 'positive' else 'negative'} "
        f"feedback about a recipe. Extract only the recipe name. "
        f"If no specific recipe name is mentioned, respond with NONE."
    )
    result, _usage = claude_client.complete(
        system_prompt="Extract recipe names from text. Respond with only the recipe name or NONE.",
        messages=[{"role": "user", "content": prompt}],
        model=MODEL,
        max_tokens=50,
    )
    name = result.strip()
    return None if name.upper() == "NONE" else name


_SIGNAL_TABLE_MAP = {"positive": "favorites", "negative": "disliked"}


def _save_recipe_signal(message: str, signal_type: str):
    recipe_name = _extract_recipe_name(message, signal_type)
    if not recipe_name:
        return
    table = _SIGNAL_TABLE_MAP[signal_type]  # KeyError if invalid
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                f"INSERT INTO {table} (recipe_name, notes, added_at) VALUES (?, ?, ?)",
                (recipe_name, message[:200], int(time.time())),
            )
    finally:
        conn.close()


def generate_meal_plan(trigger: str = "scheduled") -> str:
    """Generate a meal plan, save to Drive, log the run. Returns the plan text.

    Args:
        trigger: "scheduled" for cron jobs, "telegram" for interactive requests.
    """
    run_id = str(uuid.uuid4())
    start = time.time()
    try:
        settings = _get_settings()
        favorites = _get_favorites()
        disliked = _get_disliked()
        recent_plans = _get_recent_meal_plans()

        system_prompt = _load_system_prompt()

        context_parts = [f"Child profile: {settings}"]
        if favorites:
            context_parts.append(
                f"Favourite recipes (lean toward similar styles): {', '.join(favorites)}"
            )
        if disliked:
            context_parts.append(
                f"Disliked recipes (never include): {', '.join(disliked)}"
            )
        if recent_plans:
            context_parts.append(
                "Recent meal plans (avoid repeating these recipes): "
                + " | ".join(recent_plans[:4])
            )

        user_message = "\n".join(context_parts) + "\n\nGenerate this week's meal plan."

        response, usage = claude_client.complete(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            model=MODEL,
            max_tokens=2000,
        )

        today = datetime.date.today().isoformat()
        drive_client.create_file(
            folder_id=os.environ["DRIVE_MEAL_PLANS_FOLDER_ID"],
            name=f"meal-plan-{today}.md",
            content=response,
        )

        logger.write_run(
            {
                "run_id": run_id,
                "agent": "pa",
                "trigger": trigger,
                "task": "meal_plan",
                "status": "success",
                "tokens_input": usage.get("input_tokens"),
                "tokens_output": usage.get("output_tokens"),
                "duration_seconds": int(time.time() - start),
                "output": response[:500],
            }
        )

        return response

    except Exception as e:
        logger.write_run(
            {
                "run_id": run_id,
                "agent": "pa",
                "trigger": trigger,
                "task": "meal_plan",
                "status": "failed",
                "duration_seconds": int(time.time() - start),
                "output": str(e),
            }
        )
        raise


def meal_plan_job():
    """Scheduled entry point: generate meal plan and send to Telegram."""
    import asyncio

    import telegram as tg

    response = generate_meal_plan(trigger="scheduled")

    bot = tg.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    meal_text = _truncate_for_telegram(response, "🟦 PA · Meal plan ready!\n\n")
    asyncio.run(
        bot.send_message(
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
            text=meal_text,
        )
    )


def run(message: str, chat_id: str) -> str:
    memory = context_manager.get_memory_summary("pa")
    ctx = context_manager.get_context(chat_id, "pa")

    system_prompt = _load_system_prompt()
    if memory:
        system_prompt = f"{system_prompt}\n\n## Memory\n{memory}"

    context_manager.add_message(chat_id, "pa", "user", message)

    messages = ctx + [{"role": "user", "content": message}]

    try:
        response, _usage = claude_client.complete(
            system_prompt=system_prompt,
            messages=messages,
            model=MODEL,
            max_tokens=1000,
        )
    except Exception:
        # Add synthetic assistant message to keep alternating pattern intact
        context_manager.add_message(chat_id, "pa", "assistant", "[Error — no response generated]")
        raise

    context_manager.add_message(chat_id, "pa", "assistant", response)

    has_positive, has_negative = detect_signals(message)
    if has_positive or has_negative:
        def _detect():
            if has_positive:
                try:
                    _save_recipe_signal(message, "positive")
                except Exception:
                    pass
            if has_negative:
                try:
                    _save_recipe_signal(message, "negative")
                except Exception:
                    pass

        threading.Thread(target=_detect, daemon=True).start()

    return response


def update_memory_summary():
    updated_at = context_manager.get_memory_updated_at("pa")
    new_messages = context_manager.get_messages_since("pa", updated_at)

    if not new_messages:
        return

    existing = context_manager.get_memory_summary("pa")

    # Cap existing summary to prevent unbounded growth
    if len(existing) > MEMORY_SUMMARY_MAX_CHARS:
        existing = existing[:MEMORY_SUMMARY_MAX_CHARS]

    parts = []
    if existing:
        parts.append(f"## Existing memory summary\n{existing}")

    # Only include recent messages to bound input size
    recent = new_messages[-50:]
    parts.append(
        "## New conversation history\n"
        + "\n".join(f"{m['role'].upper()}: {m['content']}" for m in recent)
    )
    parts.append(
        "Update the summary by adding any new context, preferences, or facts learned. "
        "Do not remove or overwrite anything already accurate. Return only the updated summary. "
        "Keep the summary under 2000 characters."
    )

    updated, _usage = claude_client.complete(
        system_prompt=(
            "You maintain a memory summary for a personal assistant. "
            "Only add new information — never remove accurate existing information. "
            "Keep the summary concise — under 2000 characters."
        ),
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        model=MODEL,
        max_tokens=500,
    )

    context_manager.update_memory_summary("pa", updated[:MEMORY_SUMMARY_MAX_CHARS])


# ── Telegram handlers ────────────────────────────────────────────────────────

def _allowed(update: "Any") -> bool:
    user = update.effective_user
    return user is not None and user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])


async def _handle_meal(update: "Any", context: "Any"):
    if not _allowed(update):
        return
    import asyncio
    from functools import partial
    msg = await update.message.reply_text("🟦 PA · Working on your meal plan…")
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, partial(generate_meal_plan, trigger="telegram")
        )
        meal_text = _truncate_for_telegram(response, "🟦 PA · Meal plan ready!\n\n")
        await msg.edit_text(meal_text)
    except Exception as e:
        logging.getLogger(__name__).error("Meal plan failed: %s", e, exc_info=True)
        await msg.edit_text("🟦 PA · Meal plan failed. Check /logs for details.")


async def _handle_research(update: "Any", context: "Any"):
    if not _allowed(update):
        return
    import asyncio
    args = context.args if hasattr(context, 'args') else []
    topic = " ".join(args) if args else ""
    if not topic:
        await update.message.reply_text(
            "🟦 PA · Please provide a topic: /research [topic]"
        )
        return
    chat_id = str(update.effective_chat.id)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, run, f"[RESEARCH REQUEST] {topic}", chat_id)
    await update.message.reply_text(_truncate_for_telegram(response, "🟦 PA · "))


async def _handle_clear(update: "Any", context: "Any"):
    if not _allowed(update):
        return
    chat_id = str(update.effective_chat.id)
    context_manager.clear_context(chat_id, "pa")
    await update.message.reply_text("🟦 PA · Conversation context cleared.")


async def _handle_message(update: "Any", context: "Any"):
    if not _allowed(update):
        return
    import asyncio
    chat_id = str(update.effective_chat.id)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, run, update.message.text, chat_id)
    await update.message.reply_text(_truncate_for_telegram(response, "🟦 PA · "))


def register_handlers(app: "Any"):
    from telegram.ext import (
        CommandHandler,
        MessageHandler,
        filters,
    )

    app.add_handler(CommandHandler("meal", _handle_meal))
    app.add_handler(CommandHandler("research", _handle_research))
    app.add_handler(CommandHandler("clear", _handle_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
