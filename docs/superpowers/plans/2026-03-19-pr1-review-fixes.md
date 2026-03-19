# PR #1 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all security, DB, and agent issues identified in the PR #1 code review (issues 1-7, 11-17, 19-20), plus migrate to pyproject.toml with uv.

**Architecture:** Targeted fixes across the existing codebase — no new modules, just hardening what's there. The `complete()` return type changes from `str` to `tuple[str, dict]` which cascades to all callers. The `meal_plan_job` gets split so the Telegram handler doesn't double-send.

**Tech Stack:** Python 3.11, SQLite, uv, python-telegram-bot, anthropic SDK

**Working directory:** `/Users/samk/Documents/repos/personal-team/.worktrees/shared-infra-pa-agent`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `pyproject.toml` | Create | Package metadata, deps, dev deps, ruff/pytest config |
| `requirements.txt` | Delete | Replaced by pyproject.toml |
| `agents/db.py` | Modify | Add indexes, WAL mode |
| `agents/claude_client.py` | Modify | Return usage data, add thread lock |
| `agents/drive_client.py` | Modify | Add thread lock |
| `agents/pa/agent.py` | Modify | Fix SQL injection pattern, fix `_allowed`, decouple meal_plan_job from Telegram, save user msg before API call, make signal detection async, use usage data from complete() |
| `bot.py` | Modify | Fix `_allowed` null check, add Telegram message truncation, update complete() return handling |
| `scheduler.py` | Modify | Sanitize error messages in alerts |
| `deploy/setup.sh` | Modify | Replace `.venv/bin/python` with `uv run python` |
| `tests/test_claude_client.py` | Create | Test complete() returns usage tuple |
| `tests/test_db.py` | Create | Test indexes exist, WAL mode enabled |
| `CLAUDE.md` | Modify | Update Commands section for uv |

---

### Task 1: Migrate to pyproject.toml and enshrine uv

**Files:**
- Create: `pyproject.toml`
- Delete: `requirements.txt`
- Modify: `CLAUDE.md`
- Modify: `deploy/setup.sh`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "personal-team"
version = "0.1.0"
description = "Personal agentic team — AI agents on a Raspberry Pi"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "python-telegram-bot>=21.0",
    "apscheduler>=3.10.0",
    "python-dotenv>=1.0.0",
    "google-api-python-client>=2.100.0",
    "google-auth>=2.23.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.4.0",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Delete requirements.txt**

```bash
rm requirements.txt
```

- [ ] **Step 3: Update CLAUDE.md Commands section**

Replace the Commands section with:

```markdown
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
```

- [ ] **Step 4: Update deploy/setup.sh to use uv sync**

Replace lines that do `uv venv .venv` / `uv pip install -r requirements.txt` with:

```bash
uv sync
```

Also replace all `.venv/bin/python` references with `uv run python`:
- Line 114: `.venv/bin/python -c "from agents.db import init_db; ..."` → `uv run python -c "from agents.db import init_db; ..."`
- Line 124: `.venv/bin/python - <<'PYEOF'` → `uv run python - <<'PYEOF'`

- [ ] **Step 5: Verify uv sync works**

Run: `cd /Users/samk/Documents/repos/personal-team/.worktrees/shared-infra-pa-agent && uv sync --extra dev`
Expected: Dependencies install successfully, `uv.lock` generated.

- [ ] **Step 6: Run tests to confirm nothing broke**

Run: `cd /Users/samk/Documents/repos/personal-team/.worktrees/shared-infra-pa-agent && uv run pytest -v`
Expected: All 21 tests pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock CLAUDE.md deploy/setup.sh
git rm requirements.txt
git commit -m "chore: migrate to pyproject.toml with uv, move pytest to dev deps"
```

---

### Task 2: Add DB indexes and WAL mode (Issues #6, #7)

**Files:**
- Modify: `agents/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing test for indexes and WAL mode**

Create `tests/test_db.py`:

```python
from agents.db import get_connection


def test_wal_mode_enabled():
    conn = get_connection()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_messages_index_exists():
    conn = get_connection()
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages'"
    ).fetchall()
    conn.close()
    names = [r[0] for r in indexes]
    assert "idx_messages_chat_agent_ts" in names


def test_messages_agent_ts_index_exists():
    conn = get_connection()
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages'"
    ).fetchall()
    conn.close()
    names = [r[0] for r in indexes]
    assert "idx_messages_agent_ts" in names


def test_runs_indexes_exist():
    conn = get_connection()
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='runs'"
    ).fetchall()
    conn.close()
    names = [r[0] for r in indexes]
    assert "idx_runs_triggered_at" in names
    assert "idx_runs_agent_task_ts" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — no indexes, WAL not enabled.

- [ ] **Step 3: Add WAL mode to get_connection and indexes to init_db**

In `agents/db.py`, modify `get_connection()`:

```python
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
```

In `agents/db.py`, add to the end of the `init_db()` executescript, before the closing `""")`:

```sql
CREATE INDEX IF NOT EXISTS idx_messages_chat_agent_ts
    ON messages(chat_id, agent, timestamp DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_messages_agent_ts
    ON messages(agent, timestamp);

CREATE INDEX IF NOT EXISTS idx_runs_triggered_at
    ON runs(triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_runs_agent_task_ts
    ON runs(agent, task, triggered_at DESC);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All 4 pass.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass (21 existing + 4 new = 25).

- [ ] **Step 6: Commit**

```bash
git add agents/db.py tests/test_db.py
git commit -m "fix: add SQLite indexes and WAL mode for concurrent access"
```

---

### Task 3: Fix SQL injection pattern in _save_recipe_signal (Issue #1)

**Files:**
- Modify: `agents/pa/agent.py:105-118`

- [ ] **Step 1: Write failing test**

Add to `tests/test_pa_signals.py`:

```python
import pytest
from agents.pa.agent import _save_recipe_signal


def test_save_recipe_signal_rejects_invalid_signal_type(monkeypatch):
    # Mock _extract_recipe_name to return a name without calling Claude
    monkeypatch.setattr(
        "agents.pa.agent._extract_recipe_name", lambda msg, st: "Test Recipe"
    )
    with pytest.raises(KeyError):
        _save_recipe_signal("loved the soup", "invalid_type")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pa_signals.py::test_save_recipe_signal_rejects_invalid_signal_type -v`
Expected: FAIL — currently it would construct `f"INSERT INTO invalid_type..."` which is a sqlite3 OperationalError, not a KeyError.

- [ ] **Step 3: Fix _save_recipe_signal to use an explicit table map**

In `agents/pa/agent.py`, replace lines 105-118:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pa_signals.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add agents/pa/agent.py tests/test_pa_signals.py
git commit -m "fix: use explicit table allowlist in _save_recipe_signal to prevent SQL injection"
```

---

### Task 4: Fix _allowed null check everywhere (Issue #5)

**Files:**
- Modify: `agents/pa/agent.py:272-273`
- Modify: `bot.py:20-21`

- [ ] **Step 1: Fix _allowed in agents/pa/agent.py**

Replace lines 272-273:

```python
def _allowed(update: "Any") -> bool:
    user = update.effective_user
    return user is not None and user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])
```

- [ ] **Step 2: Fix _allowed in bot.py**

Replace lines 20-21:

```python
def _allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass (no existing tests exercise _allowed, but ensure no regressions).

- [ ] **Step 4: Commit**

```bash
git add agents/pa/agent.py bot.py
git commit -m "fix: null-check effective_user in _allowed to handle channel posts"
```

---

### Task 5: Stop leaking exceptions to Telegram (Issues #2, #3)

**Files:**
- Modify: `scheduler.py:23-30`

Note: The `_handle_meal` exception leak (Issue #2) is fixed in Task 8 when we replace the entire function.

- [ ] **Step 1: Add `import logging` to agents/pa/agent.py**

Add `import logging` to the top of `agents/pa/agent.py` (after the existing imports). This is needed by Task 8 later.

- [ ] **Step 2: Fix _alert in scheduler.py**

Replace lines 23-30:

```python
def _alert(job_name: str, error: Exception):
    bot = telegram.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    asyncio.run(
        bot.send_message(
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
            text=f"⚠️ Scheduled job failed: {job_name}. Check server logs.",
        )
    )
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add agents/pa/agent.py scheduler.py
git commit -m "fix: stop leaking exception details to Telegram messages

Also adds import logging to pa/agent.py for use in later handler fixes."
```

---

### Task 6: Add Telegram message truncation (Issue #4)

**Files:**
- Modify: `agents/pa/agent.py`
- Modify: `bot.py`

- [ ] **Step 1: Add a truncation helper to agents/pa/agent.py**

Add near the top of `agents/pa/agent.py` (after constants):

```python
TELEGRAM_MAX_LENGTH = 4096


def _truncate_for_telegram(text: str, prefix: str = "") -> str:
    max_len = TELEGRAM_MAX_LENGTH - len(prefix)
    if len(text) <= max_len:
        return prefix + text
    return prefix + text[: max_len - 3] + "..."
```

- [ ] **Step 2: Apply truncation to meal_plan_job Telegram send**

In `meal_plan_job`, replace the `bot.send_message` call (around line 168):

```python
        bot = tg.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
        meal_text = _truncate_for_telegram(response, "🟦 PA · Meal plan ready!\n\n")
        asyncio.run(
            bot.send_message(
                chat_id=os.environ["TELEGRAM_CHAT_ID"],
                text=meal_text,
            )
        )
```

- [ ] **Step 3: Apply truncation to _handle_message and _handle_research**

In `_handle_message` (around line 321):
```python
    await update.message.reply_text(_truncate_for_telegram(response, "🟦 PA · "))
```

In `_handle_research` (around line 303):
```python
    await update.message.reply_text(_truncate_for_telegram(response, "🟦 PA · "))
```

- [ ] **Step 4: Apply truncation to bot.py handle_logs**

In `bot.py`, around line 43, wrap the output:

```python
    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4093] + "..."
    await update.message.reply_text(text)
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add agents/pa/agent.py bot.py
git commit -m "fix: truncate Telegram messages to 4096 char limit"
```

---

### Task 7: Return token usage from complete() (Issue #14)

This is the largest change — it cascades to all callers.

**Files:**
- Modify: `agents/claude_client.py`
- Modify: `agents/pa/agent.py` (all calls to `claude_client.complete`)
- Create: `tests/test_claude_client.py`

- [ ] **Step 1: Write failing test for complete() return type**

Create `tests/test_claude_client.py`:

```python
from unittest.mock import MagicMock, patch
from agents.claude_client import complete


@patch("agents.claude_client._get_client")
def test_complete_returns_text_and_usage(mock_get_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello")]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_get_client.return_value.messages.create.return_value = mock_response

    text, usage = complete(
        system_prompt="test",
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5",
    )
    assert text == "Hello"
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claude_client.py -v`
Expected: FAIL — `complete()` returns a str, not a tuple.

- [ ] **Step 3: Update complete() to return (text, usage)**

In `agents/claude_client.py`, change the return type and return statement:

```python
def complete(
    system_prompt: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 1024,
) -> tuple[str, dict]:
    client = _get_client()
    last_error = None

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
            if not response.content:
                raise ClaudeAPIError("Claude API returned empty content")
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            return response.content[0].text, usage
        except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
            last_error = e
            time.sleep(2**attempt)
        except anthropic.APIError as e:
            raise ClaudeAPIError(f"Claude API error: {e}") from e

    raise ClaudeAPIError(f"Claude API failed after 3 attempts: {last_error}") from last_error
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_claude_client.py -v`
Expected: PASS.

- [ ] **Step 5: Update all callers in agents/pa/agent.py**

**`_extract_recipe_name`** (around line 95):
```python
    result, _usage = claude_client.complete(
        ...
    )
    name = result.strip()
```

**`meal_plan_job`** (around line 152):
```python
        response, usage = claude_client.complete(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            model=MODEL,
            max_tokens=2000,
        )
```

And update the logger.write_run success call to include token data:
```python
        logger.write_run(
            {
                "run_id": run_id,
                "agent": "pa",
                "trigger": "scheduled",
                "task": "meal_plan",
                "status": "success",
                "tokens_input": usage.get("input_tokens"),
                "tokens_output": usage.get("output_tokens"),
                "duration_seconds": int(time.time() - start),
                "output": response[:500],
            }
        )
```

**`run()`** (around line 211):
```python
    response, _usage = claude_client.complete(
        system_prompt=system_prompt,
        messages=messages,
        model=MODEL,
        max_tokens=1000,
    )
```

**`update_memory_summary()`** (around line 257):
```python
    updated, _usage = claude_client.complete(
        ...
    )
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add agents/claude_client.py agents/pa/agent.py tests/test_claude_client.py
git commit -m "feat: return token usage from complete() and populate cost tracking in run logs"
```

---

### Task 8: Decouple meal_plan_job from Telegram sending (Issues #11, #17)

**Files:**
- Modify: `agents/pa/agent.py`

The problem: `meal_plan_job` both generates the meal plan AND sends it to Telegram. When called from `_handle_meal`, the user gets a double message (the job sends one, then the handler edits the status message). Also, `meal_plan_job` uses `asyncio.run()` which breaks if called from an async context.

Solution: Split into `generate_meal_plan()` (pure generation + Drive upload + logging) and keep `meal_plan_job()` as the scheduled wrapper that also sends to Telegram.

- [ ] **Step 1: Extract generate_meal_plan() from meal_plan_job()**

In `agents/pa/agent.py`, replace `meal_plan_job` (lines 121-198) with two functions:

```python
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
                f"Recent meal plans (avoid repeating these recipes): "
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
```

- [ ] **Step 2: Update _handle_meal to use generate_meal_plan directly**

Replace `_handle_meal`:

```python
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
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add agents/pa/agent.py
git commit -m "refactor: decouple meal plan generation from Telegram sending to fix double-send"
```

---

### Task 9: Save user message before API call + background signal detection (Issues #12, #13)

**Files:**
- Modify: `agents/pa/agent.py` (the `run()` function)

- [ ] **Step 1: Add `import threading` to agents/pa/agent.py**

Add `import threading` to the top of `agents/pa/agent.py` (after the existing imports).

- [ ] **Step 2: Rewrite run() with save-before-call, error recovery, and threaded signals**

In `run()`, move the user message save to before `claude_client.complete`, add error recovery, and move signal detection to a background thread:

Note: We save the user message before the API call so it's not lost on failure.
If the API call fails, we add a synthetic assistant error message to maintain the
alternating user/assistant pattern required by the Anthropic API.

```python
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
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add agents/pa/agent.py
git commit -m "fix: save user message before API call, add error recovery, background signal detection"
```

---

### Task 10: Add thread locks to singleton clients (Issue #19)

Note: Background signal detection (Issue #13) was consolidated into Task 9 — the `run()` rewrite includes both save-before-call and threaded signal detection. The `import threading` in `agents/pa/agent.py` was already added in Task 9.

**Files:**
- Modify: `agents/claude_client.py`
- Modify: `agents/drive_client.py`

- [ ] **Step 1: Add threading.Lock to claude_client.py**

```python
import os
import time
import threading
import anthropic


class ClaudeAPIError(Exception):
    pass


_client = None
_client_lock = threading.Lock()


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client
```

- [ ] **Step 2: Add threading.Lock to drive_client.py**

```python
import os
import threading
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_service = None
_service_lock = threading.Lock()


def _get_service():
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                creds = service_account.Credentials.from_service_account_file(
                    os.environ["GOOGLE_CREDENTIALS_PATH"],
                    scopes=SCOPES,
                )
                _service = build("drive", "v3", credentials=creds)
    return _service
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add agents/claude_client.py agents/drive_client.py
git commit -m "fix: add thread locks to singleton API clients for APScheduler thread safety"
```

---

### Task 11: Cap memory summary size (Issue #15)

**Files:**
- Modify: `agents/pa/agent.py` (the `update_memory_summary()` function)

- [ ] **Step 1: Add max character cap to update_memory_summary**

In `update_memory_summary()`, after `context_manager.get_messages_since`, add a truncation of the existing summary if it's too long, and cap the new messages input:

```python
MEMORY_SUMMARY_MAX_CHARS = 2000


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
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add agents/pa/agent.py
git commit -m "fix: cap memory summary at 2000 chars to prevent unbounded context growth"
```

---

### Task 12: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 2: Run linter**

Run: `uv run ruff check .`
Expected: No errors (or only pre-existing ones).

- [ ] **Step 3: Verify the fix count**

Confirm all addressed issues:
- Issue 1: SQL injection pattern — Task 3 ✓
- Issue 2: Exception leak in _handle_meal — Task 8 ✓
- Issue 3: Exception leak in scheduler _alert — Task 5 ✓
- Issue 4: Telegram message length — Task 6 ✓
- Issue 5: _allowed null check — Task 4 ✓
- Issue 6: Messages table indexes — Task 2 ✓
- Issue 7: Runs table indexes — Task 2 ✓
- Issue 11: asyncio.run in meal_plan_job — Task 8 ✓
- Issue 12: User message saved after API call — Task 9 ✓
- Issue 13: Signal detection blocks response — Task 9 ✓
- Issue 14: No token/cost tracking — Task 7 ✓
- Issue 15: Memory summary unbounded — Task 11 ✓
- Issue 16: conftest fragility — acknowledged, no fix needed now
- Issue 17: Double-send meal plan — Task 8 ✓
- Issue 19: Thread-unsafe singletons — Task 10 ✓
- Issue 20: pytest in runtime deps — Task 1 ✓
- Nit: pyproject.toml + uv — Task 1 ✓
