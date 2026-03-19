import json
import os
import time
import uuid
import datetime
from pathlib import Path

from agents import claude_client, context_manager, logger, drive_client
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
    result = claude_client.complete(
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


def meal_plan_job():
    import asyncio
    import telegram as tg

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
                f"Recent meal plans (avoid repeating these recipes): "
                + " | ".join(recent_plans[:4])
            )

        user_message = "\n".join(context_parts) + "\n\nGenerate this week's meal plan."

        response = claude_client.complete(
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

        bot = tg.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
        asyncio.run(
            bot.send_message(
                chat_id=os.environ["TELEGRAM_CHAT_ID"],
                text=f"🟦 PA · Meal plan ready!\n\n{response}",
            )
        )

        logger.write_run(
            {
                "run_id": run_id,
                "agent": "pa",
                "trigger": "scheduled",
                "task": "meal_plan",
                "status": "success",
                "duration_seconds": int(time.time() - start),
                "output": response[:500],
            }
        )

    except Exception as e:
        logger.write_run(
            {
                "run_id": run_id,
                "agent": "pa",
                "trigger": "scheduled",
                "task": "meal_plan",
                "status": "failed",
                "duration_seconds": int(time.time() - start),
                "output": str(e),
            }
        )
        raise


def run(message: str, chat_id: str) -> str:
    memory = context_manager.get_memory_summary("pa")
    ctx = context_manager.get_context(chat_id, "pa")

    system_prompt = _load_system_prompt()
    if memory:
        system_prompt = f"{system_prompt}\n\n## Memory\n{memory}"

    messages = ctx + [{"role": "user", "content": message}]

    response = claude_client.complete(
        system_prompt=system_prompt,
        messages=messages,
        model=MODEL,
        max_tokens=1000,
    )

    context_manager.add_message(chat_id, "pa", "user", message)
    context_manager.add_message(chat_id, "pa", "assistant", response)

    has_positive, has_negative = detect_signals(message)
    if has_positive:
        try:
            _save_recipe_signal(message, "positive")
        except Exception:
            pass  # signal detection is best-effort
    if has_negative:
        try:
            _save_recipe_signal(message, "negative")
        except Exception:
            pass  # signal detection is best-effort

    return response


def update_memory_summary():
    updated_at = context_manager.get_memory_updated_at("pa")
    new_messages = context_manager.get_messages_since("pa", updated_at)

    if not new_messages:
        return

    existing = context_manager.get_memory_summary("pa")

    parts = []
    if existing:
        parts.append(f"## Existing memory summary\n{existing}")
    parts.append(
        "## New conversation history\n"
        + "\n".join(f"{m['role'].upper()}: {m['content']}" for m in new_messages)
    )
    parts.append(
        "Update the summary by adding any new context, preferences, or facts learned. "
        "Do not remove or overwrite anything already accurate. Return only the updated summary."
    )

    updated = claude_client.complete(
        system_prompt=(
            "You maintain a memory summary for a personal assistant. "
            "Only add new information — never remove accurate existing information."
        ),
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        model=MODEL,
        max_tokens=500,
    )

    context_manager.update_memory_summary("pa", updated)


# ── Telegram handlers ────────────────────────────────────────────────────────

def _allowed(update: "Any") -> bool:
    return update.effective_user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])


async def _handle_meal(update: "Any", context: "Any"):
    if not _allowed(update):
        return
    import asyncio
    msg = await update.message.reply_text("🟦 PA · Working on your meal plan…")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, meal_plan_job)
        await msg.edit_text("🟦 PA · Meal plan sent! Check the next message.")
    except Exception as e:
        await msg.edit_text(f"🟦 PA · Meal plan failed: {e}")


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
    await update.message.reply_text(f"🟦 PA · {response}")


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
    await update.message.reply_text(f"🟦 PA · {response}")


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
