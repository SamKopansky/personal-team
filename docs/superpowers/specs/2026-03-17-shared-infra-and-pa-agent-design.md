# Design Spec: Shared Infrastructure & Personal Assistant Agent

| | |
|---|---|
| **Date** | 2026-03-17 |
| **Status** | Approved |
| **Scope** | Full shared infrastructure + PA agent — Phase 1 of the Personal Agentic Team PRD |

---

## 1. Overview

This spec covers the implementation of the shared infrastructure and Personal Assistant (PA) agent as the first deployable slice of the Personal Agentic Team system. The shared infrastructure is designed upfront so subsequent agents (Manager, Researcher, Developer) can plug in without structural changes.

The system runs as two always-on Python processes on a Raspberry Pi, managed by systemd, communicating with the user exclusively via Telegram.

---

## 2. Project Structure

```
personal-team/
  agents/
    __init__.py
    claude_client.py        # Anthropic SDK wrapper
    logger.py               # SQLite log writer + query helpers
    context_manager.py      # SQLite-backed conversation history + agent memory
    drive_client.py         # Google Drive read/write helpers
    pa/
      agent.py              # run(), meal_plan_job(), update_memory_summary(), register_handlers()
      system-prompt.md      # Loaded fresh on every invocation
  scheduler.py              # APScheduler: PA Friday job, memory update, Drive backup
  bot.py                    # Telegram long-polling: command routing + free-form handling
  data/
    logs.db                 # SQLite database (gitignored)
  .env.example              # Documents all required env vars (no values)
  requirements.txt
  deploy/
    scheduler.service       # systemd unit file
    bot.service             # systemd unit file
    setup.sh                # Full Pi bootstrap script
```

---

## 3. Shared Infrastructure

### 3.1 `agents/claude_client.py`

Thin wrapper around the Anthropic Python SDK. Single public function:

```python
complete(system_prompt: str, messages: list[dict], model: str, max_tokens: int) -> str
```

Handles token counting and raises a typed `ClaudeAPIError` on failure. Model is passed by the caller — agents specify Haiku or Sonnet explicitly.

### 3.2 `agents/context_manager.py`

Manages per-agent conversation history backed by SQLite (`messages` table). No in-memory state — survives reboots.

**`messages` table schema:**
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `chat_id` | TEXT | Telegram chat ID |
| `agent` | TEXT | `pa \| manager \| researcher \| developer` |
| `role` | TEXT | `user \| assistant` |
| `content` | TEXT | Message text |
| `timestamp` | INTEGER | Unix timestamp |

**`agent_memory` table schema:**
| Column | Type | Description |
|---|---|---|
| `agent` | TEXT PK | Agent name |
| `summary` | TEXT | Rolling prose summary of user preferences and history |
| `updated_at` | INTEGER | Unix timestamp of last update |

Public API:
- `add_message(chat_id, agent, role, content)` — persists message
- `get_context(chat_id, agent, limit=10)` — returns last N messages as `[{role, content}]`
- `get_memory_summary(agent)` — returns the agent's prose memory summary
- `update_memory_summary(agent, summary)` — overwrites the summary row

### 3.3 `agents/logger.py`

Writes and queries structured run logs in SQLite (`runs` table). Schema matches PRD §5.1.

**`runs` table key fields:** `run_id` (UUID), `agent`, `trigger`, `triggered_at`, `task`, `status`, `tokens_input`, `tokens_output`, `cost_usd`, `duration_seconds`, `linear_ticket`, `output` (JSON blob).

Public API:
- `write_run(entry: dict)` — inserts a log row
- `get_recent_runs(n: int)` — returns last N runs as list of dicts
- `export_to_drive()` — serialises last 30 days to JSON, uploads to Drive backup folder

### 3.4 `agents/drive_client.py`

Authenticates via service account JSON at path `GOOGLE_CREDENTIALS_PATH` env var. Uses `google-api-python-client`.

Public API:
- `read_doc(file_id: str) -> str`
- `write_doc(file_id: str, content: str)`
- `append_to_doc(file_id: str, content: str)`
- `create_doc(folder_id: str, name: str, content: str) -> str` — returns new file ID

Drive file IDs for known docs are stored as env vars (never hardcoded):
- `DRIVE_MEAL_PLANS_FOLDER_ID`
- `DRIVE_CHILD_PROFILE_FILE_ID`
- `DRIVE_FAVORITES_LOG_FILE_ID`
- `DRIVE_DISLIKED_LOG_FILE_ID`
- `DRIVE_BACKUP_FOLDER_ID`

---

## 4. Telegram Bot (`bot.py`)

Single long-polling process. All handlers follow this pattern:

**Security:** Every handler checks `update.effective_user.id == int(ALLOWED_TELEGRAM_USER_ID)` as its first operation. Unknown sender → silent return, no response, no log.

**Handler registration:** Each agent module exports `register_handlers(app: Application)`. `bot.py` calls each at startup:

```python
pa.register_handlers(app)
# manager.register_handlers(app)  # added in Phase 2
```

**Phase 1 command handlers** (PA only):
| Command | Handler | Action |
|---|---|---|
| `/meal` | `handle_meal` | Sends "working on it…", calls `pa.meal_plan_job()`, edits message with result |
| `/research [topic]` | `handle_research` | Calls `pa.run(topic, context)` with research intent |
| `/logs [n]` | `handle_logs` | Calls `logger.get_recent_runs(n)`, formats as plain-English summary |

**Free-form messages:** In Phase 1 (PA only), all non-command messages route directly to `pa.run()`. The Haiku message router is added in Phase 2 when multiple agents are live.

**Response formatting:** PA responses are prefixed with `🟦 PA ·` — the pattern is established now so future agents follow it consistently.

---

## 5. PA Agent (`agents/pa/agent.py`)

### 5.1 `register_handlers(app)`

Registers `/meal`, `/research`, and the free-form message handler with the Telegram application.

### 5.2 `meal_plan_job()`

Called by the scheduler every Friday at 8am and on `/meal`. Sequence:

1. Read child profile from Drive (`DRIVE_CHILD_PROFILE_FILE_ID`) — age, vegan constraint, current preferences
2. Read favorites log from Drive (`DRIVE_FAVORITES_LOG_FILE_ID`)
3. Read disliked recipes log from Drive (`DRIVE_DISLIKED_LOG_FILE_ID`)
4. Read last 4 weeks of meal plan docs from Drive meal plans folder (for variety)
5. Call Claude Haiku with system prompt + all context above
6. Claude returns structured output: **3 recipes** + deduplicated ingredient list grouped by category
7. Save full doc to Drive meal plans folder (named `meal-plan-YYYY-MM-DD.md`)
8. Send Telegram summary: recipe names + ingredient list
9. Write log entry to SQLite via `logger.write_run()`

User can request more than 3 recipes by asking in conversation.

### 5.3 `run(message: str, chat_id: str) -> str`

Handles all free-form PA messages and `/research` requests. Sequence:

1. Load memory summary from `agent_memory` table — prepended to system prompt
2. Load last 10 messages from `messages` table for this `(chat_id, "pa")` pair
3. Append incoming user message to context
4. Call Claude Haiku with system prompt + memory summary + context
5. Persist user message and assistant response to `messages` table via `context_manager`
6. Scan response for positive signals ("loved that", "was a hit", "favorite") — if detected, append recipe to Drive favorites log
7. Scan response for negative signals ("didn't like", "won't eat", "avoid") — if detected, append recipe to Drive disliked log
8. Return response string to `bot.py`

### 5.4 `update_memory_summary()`

Called by the scheduler every Sunday at midnight. Sequence:

1. Fetch last 30 days of messages for the PA from `messages` table
2. Call Claude Haiku: "Summarise what you know about this user's preferences, their child's profile, dietary needs, and any notable patterns from these conversations."
3. Write the resulting summary to `agent_memory` table via `context_manager.update_memory_summary("pa", summary)`

### 5.5 System Prompt (`agents/pa/system-prompt.md`)

Loaded fresh on every invocation. Covers:
- Role and tone (conversational personal assistant)
- Vegan-only constraint — never suggest non-vegan recipes
- Infant nutrition context (age read from child profile at runtime)
- Meal plan format: 3 recipes with brief descriptions + grouped ingredient list
- How to signal favorites detection (explicit phrase triggers)
- How to signal disliked detection (explicit phrase triggers)
- Research response format for `/research` requests

The system prompt is editable by Sam at any time by updating the file or chatting with the agent to request changes (which the agent should acknowledge and propose as edits).

---

## 6. Scheduler (`scheduler.py`)

APScheduler process with four jobs:

| Job | Schedule | Function |
|---|---|---|
| Meal plan | Friday 8am | `pa.meal_plan_job()` |
| Memory summary update | Sunday midnight | `pa.update_memory_summary()` |
| SQLite → Drive backup | Daily 2am | `logger.export_to_drive()` |

Each job is wrapped in try/except. On failure, sends a Telegram alert to `ALLOWED_TELEGRAM_USER_ID` with the error summary so failures are never silent.

---

## 7. Pi Setup & Deployment

### 7.1 `deploy/setup.sh` — Bootstrap script

Runs once on a fresh Pi. Steps:

1. `apt` install: Python 3.11, git, sqlite3, fail2ban
2. Install `uv` (Python package manager)
3. Clone repo to `/home/pi/personal-team`
4. Create virtualenv with `uv venv`, install dependencies with `uv pip install -r requirements.txt`
5. Prompt for all env vars → write to `/home/pi/.env` (outside repo, `chmod 600`)
6. Prompt to paste Drive service account JSON → write to `/home/pi/.config/personal-team/drive-credentials.json` (`chmod 600`)
7. SSH hardening:
   - Disable password authentication (`PasswordAuthentication no` in `sshd_config`)
   - Add `AllowUsers pi`
   - Restart `sshd`
8. Configure `fail2ban` for SSH (default jail, bans after 5 failed attempts)
9. Install and configure Tailscale (`curl -fsSL https://tailscale.com/install.sh | sh`, `tailscale up`)
10. Copy systemd unit files to `/etc/systemd/system/`, enable and start `bot.service` and `scheduler.service`
11. Smoke test: send a Telegram message confirming the bot is live

### 7.2 Secrets management

- All secrets are env vars in `/home/pi/.env` — gitignored, `chmod 600`, outside the repo directory
- Drive service account JSON at `/home/pi/.config/personal-team/drive-credentials.json` — `chmod 600`
- `.env.example` (committed) documents all required key names without values
- No secrets ever touch git

### 7.3 Deploying code updates

```bash
cd /home/pi/personal-team && git pull && sudo systemctl restart bot scheduler
```

### 7.4 Security posture

- **Telegram long-polling**: Pi makes outbound connections only — no inbound internet exposure for the bot
- **SSH key-only auth**: password authentication disabled at the system level
- **fail2ban**: blocks IPs after 5 failed SSH attempts
- **Tailscale**: SSH accessible remotely only through the authenticated Tailscale tunnel — local network SSH can optionally be restricted to Tailscale interface only
- **Drive service account**: scoped to specific folders only, not full Drive access
- **Credentials**: outside repo, `chmod 600`, never committed

---

## 8. Data Architecture Summary

| Data | Store | Location |
|---|---|---|
| Agent run logs | SQLite | `data/logs.db` → `runs` table |
| Conversation history | SQLite | `data/logs.db` → `messages` table |
| Agent memory summaries | SQLite | `data/logs.db` → `agent_memory` table |
| Meal plan docs | Google Drive | `meal-plans/` folder |
| Child profile | Google Drive | Single doc, updated by PA on request |
| Favorites log | Google Drive | Append-only doc |
| Disliked recipes log | Google Drive | Append-only doc |
| Log backup | Google Drive | Daily JSON export from SQLite |

---

## 9. Environment Variables

Documented in `.env.example`:

```
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
ALLOWED_TELEGRAM_USER_ID=
GOOGLE_CREDENTIALS_PATH=/home/pi/.config/personal-team/drive-credentials.json
DRIVE_MEAL_PLANS_FOLDER_ID=
DRIVE_CHILD_PROFILE_FILE_ID=
DRIVE_FAVORITES_LOG_FILE_ID=
DRIVE_DISLIKED_LOG_FILE_ID=
DRIVE_BACKUP_FOLDER_ID=
```

---

## 10. Out of Scope (Phase 1)

- Message router (Haiku classifier) — added in Phase 2 when multiple agents are live
- Manager, Researcher, Developer agents
- GitHub Actions CI/CD
- Observability dashboard (Phase 3)
- `/approve`, `/status`, `/dev`, `/plan` commands
