import datetime
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from agents import claude_client, context_manager, logger
from agents.integrations import linear

MODEL = "claude-haiku-4-5"
SYSTEM_PROMPT_PATH = Path(__file__).parent / "system-prompt.md"
TELEGRAM_MAX_LENGTH = 4096

_log = logging.getLogger(__name__)

# In-memory store of pending plan proposals keyed by short plan ID.
# Plans are lost on bot restart (acceptable for Phase 1).
_pending_plans: dict[str, dict] = {}


def _truncate_for_telegram(text: str, prefix: str = "") -> str:
    max_len = TELEGRAM_MAX_LENGTH - len(prefix)
    if len(text) <= max_len:
        return prefix + text
    return prefix + text[: max_len - 3] + "..."


def _load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text()


def _allowed(update: Any) -> bool:
    user = update.effective_user
    return user is not None and user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])


# ── Core functions ────────────────────────────────────────────────────────────


def daily_digest_job():
    """Scheduled 9am job: fetch Linear board state and send digest to Telegram."""
    import asyncio

    import telegram as tg

    run_id = str(uuid.uuid4())
    start = time.time()

    try:
        board = linear.get_board_summary()
    except Exception as e:
        _log.warning("Linear unavailable for digest: %s", e)
        board = None

    try:
        # Monthly cost from run log
        from agents.db import get_connection

        conn = get_connection()
        try:
            today = datetime.date.today()
            month_start_ts = int(datetime.datetime(today.year, today.month, 1).timestamp())
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM runs WHERE triggered_at > ?",
                (month_start_ts,),
            ).fetchone()
            monthly_cost = float(row["total"]) if row else 0.0
        finally:
            conn.close()

        today_str = datetime.date.today().strftime("%A %B %d")
        lines = [f"📊 Manager digest — {today_str}\n"]

        if board:
            if board["in_progress"]:
                lines.append("▶️ In progress:")
                for t in board["in_progress"][:5]:
                    lines.append(f"  • {t['identifier']}: {t['title']}")
            if board["in_review"]:
                lines.append("👀 In review (needs your approval):")
                for t in board["in_review"][:5]:
                    lines.append(f"  • {t['identifier']}: {t['title']}")
            if board["blocked"]:
                lines.append("⛔ Blocked:")
                for t in board["blocked"][:3]:
                    lines.append(f"  • {t['identifier']}: {t['title']}")
            if board["ready"]:
                lines.append(f"🟡 Ready: {len(board['ready'])} ticket(s) queued")
            if not any(board.values()):
                lines.append("Board is clear — no active tickets.")
        else:
            lines.append("⚠️ Could not reach Linear.")

        lines.append(f"\nBudget: ${monthly_cost:.2f} used of $50.00 this month.")
        digest = "\n".join(lines)

        bot = tg.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
        asyncio.run(
            bot.send_message(
                chat_id=os.environ["TELEGRAM_CHAT_ID"],
                text=_truncate_for_telegram(digest),
            )
        )

        logger.write_run(
            {
                "run_id": run_id,
                "agent": "manager",
                "trigger": "scheduled",
                "task": "daily_digest",
                "status": "success",
                "duration_seconds": int(time.time() - start),
                "output": digest[:500],
            }
        )

    except Exception as e:
        logger.write_run(
            {
                "run_id": run_id,
                "agent": "manager",
                "trigger": "scheduled",
                "task": "daily_digest",
                "status": "failed",
                "duration_seconds": int(time.time() - start),
                "output": str(e),
            }
        )
        raise


def get_status() -> str:
    """Return a formatted board status string for /status command."""
    try:
        board = linear.get_board_summary()
    except Exception as e:
        return f"🟡 Manager · Could not reach Linear: {e}"

    lines = ["🟡 Manager · Board status\n"]
    if board["in_progress"]:
        lines.append("▶️ In progress:")
        for t in board["in_progress"][:5]:
            lines.append(f"  • {t['identifier']}: {t['title']}")
    if board["in_review"]:
        lines.append("👀 In review (needs your approval):")
        for t in board["in_review"][:5]:
            lines.append(f"  • {t['identifier']}: {t['title']}")
    if board["blocked"]:
        lines.append("⛔ Blocked:")
        for t in board["blocked"][:3]:
            lines.append(f"  • {t['identifier']}: {t['title']}")
    if board["ready"]:
        lines.append(f"🟡 Ready: {len(board['ready'])} ticket(s)")
    if not any(board.values()):
        lines.append("No active tickets.")
    return "\n".join(lines)


def plan_command(description: str, chat_id: str) -> tuple[str, str]:
    """Break a description into Linear ticket proposals.

    Returns (plan_id, response_text). Stores plan in _pending_plans.
    """
    run_id = str(uuid.uuid4())
    start = time.time()

    system_prompt = _load_system_prompt()
    user_msg = (
        f"Break this project description into Linear ticket proposals:\n\n{description}\n\n"
        "Return a numbered list of tickets. Format each as:\n"
        "N. **Title** — Brief description of acceptance criteria.\n\n"
        "Keep titles under 60 characters. Aim for 3–7 tickets."
    )

    response, usage = claude_client.complete(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
        model=MODEL,
        max_tokens=800,
    )

    # Use an 8-char UUID prefix as a short, typeable plan ID
    plan_id = str(uuid.uuid4())[:8]
    _pending_plans[plan_id] = {
        "id": plan_id,
        "description": description,
        "response": response,
        "chat_id": chat_id,
        "created_at": time.time(),
    }

    logger.write_run(
        {
            "run_id": run_id,
            "agent": "manager",
            "trigger": "telegram_command",
            "task": "plan",
            "status": "success",
            "tokens_input": usage.get("input_tokens"),
            "tokens_output": usage.get("output_tokens"),
            "duration_seconds": int(time.time() - start),
            "output": response[:500],
        }
    )

    return plan_id, response


def approve_plan(plan_id: str) -> str:
    """Create Linear tickets from a pending plan. Returns a status message."""
    plan = _pending_plans.get(plan_id)
    if not plan:
        return "🟡 Manager · No pending plan found with that ID. Plans expire on bot restart."

    team_id = os.environ.get("LINEAR_TEAM_ID", "")
    if not team_id:
        return "🟡 Manager · LINEAR_TEAM_ID not configured — cannot create tickets."

    run_id = str(uuid.uuid4())
    start = time.time()

    # Extract ticket titles from the plan text
    extract_prompt = (
        "Extract only the ticket titles from this plan. "
        "Return one title per line, plain text only — no numbers, bullets, or descriptions."
    )
    try:
        titles_text, _ = claude_client.complete(
            system_prompt=extract_prompt,
            messages=[{"role": "user", "content": plan["response"]}],
            model=MODEL,
            max_tokens=400,
        )
        titles = [
            t.strip().lstrip("0123456789.-• ")
            for t in titles_text.strip().splitlines()
            if t.strip()
        ]

        created = []
        for title in titles[:10]:  # cap at 10 tickets
            if not title:
                continue
            ticket = linear.create_ticket(team_id, title, plan["description"])
            created.append(ticket["identifier"])

        del _pending_plans[plan_id]

        logger.write_run(
            {
                "run_id": run_id,
                "agent": "manager",
                "trigger": "telegram_command",
                "task": "approve_plan",
                "status": "success",
                "duration_seconds": int(time.time() - start),
                "output": f"Created: {', '.join(created)}",
            }
        )

        return f"🟡 Manager · Created {len(created)} ticket(s): {', '.join(created)}"

    except Exception as e:
        logger.write_run(
            {
                "run_id": run_id,
                "agent": "manager",
                "trigger": "telegram_command",
                "task": "approve_plan",
                "status": "failed",
                "duration_seconds": int(time.time() - start),
                "output": str(e),
            }
        )
        raise


def run(message: str, chat_id: str) -> str:
    """Handle a free-form message routed to Manager."""
    ctx = context_manager.get_context(chat_id, "manager")
    system_prompt = _load_system_prompt()

    # Inject current board state so Manager can answer status questions
    try:
        board = linear.get_board_summary()
        in_prog = [f"{t['identifier']}: {t['title']}" for t in board.get("in_progress", [])]
        in_rev = [f"{t['identifier']}: {t['title']}" for t in board.get("in_review", [])]
        board_ctx = (
            f"In progress: {', '.join(in_prog) or 'none'}. "
            f"In review: {', '.join(in_rev) or 'none'}. "
            f"Ready: {len(board.get('ready', []))} tickets."
        )
        system_prompt = f"{system_prompt}\n\n## Current Board\n{board_ctx}"
    except Exception:
        pass  # proceed without board context if Linear is unavailable

    context_manager.add_message(chat_id, "manager", "user", message)
    messages = ctx + [{"role": "user", "content": message}]

    try:
        response, _usage = claude_client.complete(
            system_prompt=system_prompt,
            messages=messages,
            model=MODEL,
            max_tokens=800,
        )
    except Exception:
        context_manager.add_message(
            chat_id, "manager", "assistant", "[Error — no response generated]"
        )
        raise

    context_manager.add_message(chat_id, "manager", "assistant", response)
    return response


# ── Telegram handlers ────────────────────────────────────────────────────────


async def _handle_status(update: Any, context: Any):
    if not _allowed(update):
        return
    import asyncio

    loop = asyncio.get_event_loop()
    try:
        status = await loop.run_in_executor(None, get_status)
        await update.message.reply_text(_truncate_for_telegram(status))
    except Exception as e:
        _log.error("Status failed: %s", e, exc_info=True)
        await update.message.reply_text("🟡 Manager · Status check failed. Check /logs.")


async def _handle_plan(update: Any, context: Any):
    if not _allowed(update):
        return
    import asyncio

    args = context.args if hasattr(context, "args") else []
    description = " ".join(args) if args else ""
    if not description:
        await update.message.reply_text("🟡 Manager · Usage: /plan [project description]")
        return
    chat_id = str(update.effective_chat.id)
    msg = await update.message.reply_text("🟡 Manager · Planning…")
    try:
        loop = asyncio.get_event_loop()
        plan_id, response = await loop.run_in_executor(None, plan_command, description, chat_id)
        text = (
            f"🟡 Manager · Here's the breakdown:\n\n{response}\n\n"
            f"Reply /approve {plan_id} to create these in Linear, or tell me what to change."
        )
        await msg.edit_text(_truncate_for_telegram(text))
    except Exception as e:
        _log.error("Plan failed: %s", e, exc_info=True)
        await msg.edit_text("🟡 Manager · Planning failed. Check /logs.")


async def _handle_approve(update: Any, context: Any):
    if not _allowed(update):
        return
    import asyncio

    args = context.args if hasattr(context, "args") else []
    if not args:
        await update.message.reply_text("🟡 Manager · Usage: /approve [plan-id]")
        return
    plan_id = args[0]
    msg = await update.message.reply_text("🟡 Manager · Creating tickets…")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, approve_plan, plan_id)
        await msg.edit_text(_truncate_for_telegram(result))
    except Exception as e:
        _log.error("Approve failed: %s", e, exc_info=True)
        await msg.edit_text("🟡 Manager · Ticket creation failed. Check /logs.")


def register_handlers(app: Any):
    from telegram.ext import CommandHandler

    app.add_handler(CommandHandler("status", _handle_status))
    app.add_handler(CommandHandler("plan", _handle_plan))
    app.add_handler(CommandHandler("approve", _handle_approve))
