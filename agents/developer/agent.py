import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from agents import claude_client, context_manager, logger
from agents.integrations import github, linear

MODEL = "claude-sonnet-4-6"
SYSTEM_PROMPT_PATH = Path(__file__).parent / "system-prompt.md"
TELEGRAM_MAX_LENGTH = 4096

_log = logging.getLogger(__name__)


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


def _slugify(title: str) -> str:
    """Convert a ticket title to a URL-safe branch-name slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug[:40].rstrip("-")


# ── Core functions ────────────────────────────────────────────────────────────


def morning_pickup_job():
    """Scheduled morning job: pick the highest-priority Ready ticket and open a PR."""
    import asyncio

    import telegram as tg

    run_id = str(uuid.uuid4())
    start = time.time()

    try:
        tickets = linear.get_ready_tickets()
        if not tickets:
            _log.info("Developer morning pickup: no ready tickets found")
            return

        ticket = tickets[0]
        ticket_id = ticket["identifier"]
        title = ticket["title"]
        description = ticket.get("description") or "(no description)"

        system_prompt = _load_system_prompt()
        plan_prompt = (
            f"Ticket: {ticket_id} — {title}\n\n"
            f"Description:\n{description}\n\n"
            "Write a PR description for this ticket following the template in your instructions. "
            "Include: approach, files to change, testing strategy, and any concerns."
        )

        plan, usage = claude_client.complete(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": plan_prompt}],
            model=MODEL,
            max_tokens=1200,
        )

        branch_name = f"feature/{ticket_id.lower()}-{_slugify(title)}"
        pr_url = None

        repo = os.environ.get("DEFAULT_GITHUB_REPO", "")
        if repo:
            try:
                sha = github.get_default_branch_sha(repo)
                github.create_branch(repo, branch_name, sha)
                pr_body = f"## Linear Ticket\n{ticket_id}: {title}\n\n{plan}"
                pr = github.create_pr(
                    repo=repo,
                    title=f"{ticket_id}: {title}",
                    body=pr_body,
                    head=branch_name,
                )
                pr_url = pr.get("html_url", "")
            except Exception as e:
                _log.warning("GitHub PR creation failed: %s", e)

        lines = [f"🟩 Developer · Picked up {ticket_id}: {title}\n"]
        lines.append(f"Branch: `{branch_name}`")
        if pr_url:
            lines.append(f"PR: {pr_url}")
        else:
            lines.append("(No PR created — DEFAULT_GITHUB_REPO not configured or GitHub error)")
        lines.append("\nAwaiting your review and merge approval.")

        bot = tg.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
        asyncio.run(
            bot.send_message(
                chat_id=os.environ["TELEGRAM_CHAT_ID"],
                text=_truncate_for_telegram("\n".join(lines)),
            )
        )

        logger.write_run(
            {
                "run_id": run_id,
                "agent": "developer",
                "trigger": "scheduled",
                "task": f"pickup_{ticket_id}",
                "status": "success",
                "tokens_input": usage.get("input_tokens"),
                "tokens_output": usage.get("output_tokens"),
                "duration_seconds": int(time.time() - start),
                "output": pr_url or branch_name,
            }
        )

    except Exception as e:
        logger.write_run(
            {
                "run_id": run_id,
                "agent": "developer",
                "trigger": "scheduled",
                "task": "morning_pickup",
                "status": "failed",
                "duration_seconds": int(time.time() - start),
                "output": str(e),
            }
        )
        raise


def run(task: str, chat_id: str) -> str:
    """Handle a /dev ad-hoc task — plan the implementation and return the plan."""
    ctx = context_manager.get_context(chat_id, "developer")
    system_prompt = _load_system_prompt()

    context_manager.add_message(chat_id, "developer", "user", task)
    messages = ctx + [{"role": "user", "content": task}]

    try:
        response, _usage = claude_client.complete(
            system_prompt=system_prompt,
            messages=messages,
            model=MODEL,
            max_tokens=1500,
        )
    except Exception:
        context_manager.add_message(
            chat_id, "developer", "assistant", "[Error — no response generated]"
        )
        raise

    context_manager.add_message(chat_id, "developer", "assistant", response)
    return response


# ── Telegram handlers ────────────────────────────────────────────────────────


async def _handle_dev(update: Any, context: Any):
    if not _allowed(update):
        return
    import asyncio

    args = context.args if hasattr(context, "args") else []
    task = " ".join(args) if args else ""
    if not task:
        await update.message.reply_text("🟩 Developer · Usage: /dev [task description]")
        return
    chat_id = str(update.effective_chat.id)
    msg = await update.message.reply_text("🟩 Developer · Working on it…")
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, run, task, chat_id)
        await msg.edit_text(
            _truncate_for_telegram(response, "🟩 Developer · "), parse_mode="Markdown"
        )
    except Exception as e:
        _log.error("Dev command failed: %s", e, exc_info=True)
        await msg.edit_text("🟩 Developer · Something went wrong. Check /logs.")


def register_handlers(app: Any):
    from telegram.ext import CommandHandler

    app.add_handler(CommandHandler("dev", _handle_dev))
