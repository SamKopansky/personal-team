# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A personal agentic team — four AI agents (PA, Manager, Researcher, Developer) that run on a Raspberry Pi, communicate through Telegram, and autonomously handle productivity and software development tasks. See `Personal-Agentic-Team-PRD-v1.2.md` for the full spec.

## Target Stack

- **Runtime**: Python on Raspberry Pi, managed by systemd
- **Scheduling**: APScheduler in `scheduler.py`
- **Telegram**: `python-telegram-bot` in `bot.py` (long-polling)
- **AI**: Anthropic Claude API — Sonnet for Developer/Researcher, Haiku for PA/Manager/Router
- **Integrations**: Linear API, GitHub API (per-agent PATs), Google Drive API (OAuth service account)
- **CI**: GitHub Actions — ESLint/Prettier, Ruff, Jest, Pytest, Playwright (Phase 2+)
- **Frontend**: Next.js on Vercel (Phase 3 observability dashboard)

## Architecture

Two always-running Pi processes share a common `agents/` package:

```
scheduler.py      # APScheduler cron jobs (PA Friday, Manager 9am, Developer morning)
bot.py            # Telegram long-polling, command routing, free-form message handling

agents/
  __init__.py
  claude_client.py        # Anthropic SDK wrapper
  router.py               # Haiku classifier → { agent, confidence, reason }
  context_manager.py      # Per-agent rolling 10-msg window, 30-min inactivity reset
  logger.py               # Structured JSON log writer
  integrations/
    linear.py
    github.py
    drive.py
  pa/
    agent.py
    system-prompt.md      # Loaded fresh on every invocation
  manager/
    agent.py
    system-prompt.md
    inbox/ideas.md        # Sam drops rough ideas here; Manager checks daily
  researcher/
    agent.py
    system-prompt.md
  developer/
    agent.py
    system-prompt.md

logs/YYYY-MM-DD/[agent]-[run-id].json   # Structured run logs
research/[ticket-id]-[slug].md          # Researcher output briefs
```

## Key Conventions

**Security**: Every Telegram message handler checks sender ID against a hardcoded allowlist as its first operation. Unknown users are silently dropped — no response, no log.

**System prompts**: Loaded fresh from `agents/[name]/system-prompt.md` on every agent invocation (both scheduled and bot-triggered). Never hardcode prompts in Python.

**Message routing**: Free-form Telegram messages go through the Haiku router first. Auto-route threshold is `confidence >= 0.75`; below that, send inline clarification buttons. Developer is never a direct routing target for free-form — always route through Manager first (except `/dev` command).

**Conversation context**: Stored in-memory Python dict keyed by `(chat_id, agent)`. Capped at 10 messages (5 exchanges). Reset after 30 minutes of inactivity. Scheduled jobs are always stateless — they never use Telegram context.

**Logging**: Every agent run (scheduled or on-demand) must write a structured JSON log entry. See PRD §5.1 for the full schema. Fields include `run_id`, `agent`, `trigger`, `tokens_input`, `tokens_output`, `cost_usd`, `router_decision`, and `steps`.

**Model assignment**:
- `claude-sonnet-4-6` — Developer, Researcher
- `claude-haiku-4-5` — Manager, PA, Message Router

**GitHub accounts**: Three separate agent accounts with different permission levels. Developer (`sam-agent-developer`) has Write but cannot merge. All merges require Sam's approval.

**Credentials**: All API keys/tokens are env vars on the Pi. A `.env.example` documents required keys. Nothing is committed.

## Commands

```bash
# Install dependencies
uv sync

# Install with dev dependencies
uv sync --extra dev

# Run the scheduler
uv run python scheduler.py

# Run the Telegram bot
uv run python bot.py

# Run Python tests
uv run pytest

# Lint Python
uv run ruff check .

# Format Python
uv run ruff format .
```

## Implementation Phases

- **Phase 1** (Weeks 1–3): Ops repo, logging, Pi scheduler, Telegram bot, message router, conversation context, PA + Manager agents, Developer basic PR flow, `/status` and `/logs` commands
- **Phase 2** (Weeks 4–8): Agent GitHub accounts, autonomous git ops, CI pipeline, Claude review bot, agentic QA loop, Researcher agent, Manager prompt proposals
- **Phase 3** (Month 3+): Next.js observability dashboard, router analytics, multi-agent coordination, cost optimization
