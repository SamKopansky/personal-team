# Shared Infrastructure & PA Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full shared infrastructure and Personal Assistant agent for the Personal Agentic Team system, deployable to a Raspberry Pi.

**Architecture:** Two always-on Python processes (`bot.py`, `scheduler.py`) share an `agents/` package. All persistent state lives in SQLite (`data/logs.db`). Google Drive is used only for meal plan docs and daily DB backups. The Telegram bot is the sole user interface.

**Tech Stack:** Python 3.11, `python-telegram-bot` v21+, `apscheduler`, `anthropic`, `google-api-python-client`, `python-dotenv`, `pytest`, `uv`, SQLite, systemd

---

## File Map

| File | Purpose |
|------|---------|
| `agents/db.py` | SQLite connection + schema initialisation |
| `agents/context_manager.py` | Conversation history, session boundary, agent memory |
| `agents/logger.py` | Run log write/query, Drive backup |
| `agents/claude_client.py` | Anthropic SDK wrapper with retry |
| `agents/drive_client.py` | Drive API v3: create file, upload backup |
| `agents/pa/agent.py` | PA entry points: `run()`, `meal_plan_job()`, `update_memory_summary()`, `register_handlers()` |
| `agents/pa/system-prompt.md` | PA system prompt, loaded fresh per invocation |
| `bot.py` | Telegram long-polling process |
| `scheduler.py` | APScheduler cron process |
| `tests/conftest.py` | Shared pytest fixture: in-memory SQLite redirect |
| `tests/test_context_manager.py` | Unit tests for context manager |
| `tests/test_logger.py` | Unit tests for logger |
| `tests/test_pa_signals.py` | Unit tests for PA signal detection |
| `deploy/bot.service` | systemd unit for bot |
| `deploy/scheduler.service` | systemd unit for scheduler |
| `deploy/setup.sh` | Full Pi bootstrap script |
| `requirements.txt` | Python dependencies |
| `.env.example` | Env var documentation |
| `.gitignore` | Ignores `data/`, `.env`, `.venv/` |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `agents/__init__.py`
- Create: `agents/pa/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
anthropic>=0.40.0
python-telegram-bot>=21.0
apscheduler>=3.10.0
python-dotenv>=1.0.0
google-api-python-client>=2.100.0
google-auth>=2.23.0
pytest>=8.0.0
```

- [ ] **Step 2: Create `.env.example`**

```
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
ALLOWED_TELEGRAM_USER_ID=
TELEGRAM_CHAT_ID=
GOOGLE_CREDENTIALS_PATH=/home/pi/.config/personal-team/drive-credentials.json
DRIVE_MEAL_PLANS_FOLDER_ID=
DRIVE_BACKUP_FOLDER_ID=
```

- [ ] **Step 3: Create `.gitignore`**

```
data/
.env
.venv/
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
```

- [ ] **Step 4: Create empty `__init__.py` files**

```bash
touch agents/__init__.py agents/pa/__init__.py tests/__init__.py
mkdir -p data
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example .gitignore agents/__init__.py agents/pa/__init__.py tests/__init__.py
git commit -m "chore: project scaffolding"
```

---

## Task 2: Database Layer

**Files:**
- Create: `agents/db.py`

- [ ] **Step 1: Write `agents/db.py`**

```python
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "logs.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = get_connection()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                trigger TEXT NOT NULL,
                triggered_at INTEGER NOT NULL,
                task TEXT,
                status TEXT NOT NULL,
                tokens_input INTEGER,
                tokens_output INTEGER,
                cost_usd REAL,
                duration_seconds INTEGER,
                linear_ticket TEXT,
                output TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_memory (
                agent TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_name TEXT NOT NULL,
                notes TEXT,
                added_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS disliked (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_name TEXT NOT NULL,
                notes TEXT,
                added_at INTEGER NOT NULL
            );
        """)
    conn.close()
```

- [ ] **Step 2: Verify `init_db()` runs without error**

```bash
python -c "from agents.db import init_db; init_db(); print('OK')"
```

Expected: `OK` and `data/logs.db` exists.

- [ ] **Step 3: Commit**

```bash
git add agents/db.py
git commit -m "feat: SQLite schema and connection helper"
```

---

## Task 3: Context Manager

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_context_manager.py`
- Create: `agents/context_manager.py`

- [ ] **Step 1: Write `tests/conftest.py`**

This fixture redirects `DB_PATH` to a temp file for every test, so no test touches the real database.

```python
import pytest
from agents.db import init_db


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("agents.db.DB_PATH", db_path)
    init_db()
    yield
```

- [ ] **Step 2: Write `tests/test_context_manager.py`**

```python
import time
import pytest
from agents import context_manager
from agents.db import get_connection


def test_add_and_get_context():
    context_manager.add_message("chat1", "pa", "user", "hello")
    context_manager.add_message("chat1", "pa", "assistant", "hi there")
    result = context_manager.get_context("chat1", "pa")
    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "hello"
    assert result[1]["role"] == "assistant"


def test_get_context_respects_limit():
    for i in range(15):
        context_manager.add_message("chat1", "pa", "user", f"msg {i}")
    result = context_manager.get_context("chat1", "pa", limit=10)
    assert len(result) == 10


def test_get_context_24h_session_boundary():
    context_manager.add_message("chat1", "pa", "user", "old message")
    conn = get_connection()
    old_ts = int(time.time()) - (25 * 60 * 60)
    with conn:
        conn.execute(
            "UPDATE messages SET timestamp = ? WHERE chat_id = 'chat1' AND agent = 'pa'",
            (old_ts,),
        )
    conn.close()
    assert context_manager.get_context("chat1", "pa") == []


def test_get_context_within_24h():
    context_manager.add_message("chat1", "pa", "user", "recent message")
    result = context_manager.get_context("chat1", "pa")
    assert len(result) == 1


def test_clear_context_only_affects_correct_pair():
    context_manager.add_message("chat1", "pa", "user", "msg for pa")
    context_manager.add_message("chat1", "manager", "user", "msg for manager")
    context_manager.clear_context("chat1", "pa")
    assert context_manager.get_context("chat1", "pa") == []
    assert len(context_manager.get_context("chat1", "manager")) == 1


def test_memory_summary_roundtrip():
    context_manager.update_memory_summary("pa", "User likes spicy food")
    assert context_manager.get_memory_summary("pa") == "User likes spicy food"


def test_memory_summary_empty_when_not_set():
    assert context_manager.get_memory_summary("pa") == ""


def test_get_messages_since_filters_by_timestamp():
    old_ts = int(time.time()) - 1000
    context_manager.add_message("chat1", "pa", "user", "old")
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE messages SET timestamp = ? WHERE content = 'old'", (old_ts,)
        )
    conn.close()
    context_manager.add_message("chat1", "pa", "user", "new")
    since = old_ts + 1
    msgs = context_manager.get_messages_since("pa", since)
    assert len(msgs) == 1
    assert msgs[0]["content"] == "new"
```

- [ ] **Step 3: Run tests — expect all to fail**

```bash
pytest tests/test_context_manager.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` (module doesn't exist yet).

- [ ] **Step 4: Write `agents/context_manager.py`**

```python
import time
from agents.db import get_connection

SESSION_TIMEOUT = 24 * 60 * 60  # seconds


def add_message(chat_id: str, agent: str, role: str, content: str):
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO messages (chat_id, agent, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (chat_id, agent, role, content, int(time.time())),
        )
    conn.close()


def get_context(chat_id: str, agent: str, limit: int = 10) -> list[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(timestamp) as last_ts FROM messages WHERE chat_id = ? AND agent = ?",
        (chat_id, agent),
    ).fetchone()

    if row["last_ts"] is None or (time.time() - row["last_ts"]) > SESSION_TIMEOUT:
        conn.close()
        return []

    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? AND agent = ? "
        "ORDER BY timestamp DESC LIMIT ?",
        (chat_id, agent, limit),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_context(chat_id: str, agent: str):
    conn = get_connection()
    with conn:
        conn.execute(
            "DELETE FROM messages WHERE chat_id = ? AND agent = ?",
            (chat_id, agent),
        )
    conn.close()


def get_memory_summary(agent: str) -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT summary FROM agent_memory WHERE agent = ?", (agent,)
    ).fetchone()
    conn.close()
    return row["summary"] if row else ""


def update_memory_summary(agent: str, summary: str):
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_memory (agent, summary, updated_at) VALUES (?, ?, ?)",
            (agent, summary, int(time.time())),
        )
    conn.close()


def get_memory_updated_at(agent: str) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT updated_at FROM agent_memory WHERE agent = ?", (agent,)
    ).fetchone()
    conn.close()
    return row["updated_at"] if row else 0


def get_messages_since(agent: str, since_timestamp: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE agent = ? AND timestamp > ? ORDER BY timestamp ASC",
        (agent, since_timestamp),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]
```

- [ ] **Step 5: Run tests — expect all to pass**

```bash
pytest tests/test_context_manager.py -v
```

Expected: 8 tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add agents/context_manager.py tests/conftest.py tests/test_context_manager.py
git commit -m "feat: SQLite-backed context manager with 24h session boundary"
```

---

## Task 4: Logger

**Files:**
- Create: `tests/test_logger.py`
- Create: `agents/logger.py`

- [ ] **Step 1: Write `tests/test_logger.py`**

```python
import time
import pytest
from agents import logger


def test_write_and_read_run():
    entry = {
        "run_id": "test-001",
        "agent": "pa",
        "trigger": "scheduled",
        "task": "meal_plan",
        "status": "success",
        "tokens_input": 100,
        "tokens_output": 200,
        "cost_usd": 0.001,
        "duration_seconds": 5,
    }
    logger.write_run(entry)
    runs = logger.get_recent_runs(1)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "test-001"
    assert runs[0]["status"] == "success"
    assert runs[0]["cost_usd"] == pytest.approx(0.001)


def test_write_run_generates_run_id_if_missing():
    logger.write_run({"agent": "pa", "trigger": "scheduled", "status": "success"})
    runs = logger.get_recent_runs(1)
    assert runs[0]["run_id"] is not None


def test_get_recent_runs_returns_n_most_recent():
    for i in range(5):
        logger.write_run({"agent": "pa", "trigger": "test", "status": "success", "run_id": f"r{i}"})
    runs = logger.get_recent_runs(3)
    assert len(runs) == 3


def test_get_recent_runs_descending_order():
    for i in range(3):
        logger.write_run({
            "run_id": f"ord-{i}",
            "agent": "pa",
            "trigger": "test",
            "status": "success",
            "triggered_at": 1000 + i,
        })
    runs = logger.get_recent_runs(3)
    assert runs[0]["run_id"] == "ord-2"
    assert runs[2]["run_id"] == "ord-0"


def test_get_recent_runs_empty():
    assert logger.get_recent_runs(5) == []
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_logger.py -v
```

Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Write `agents/logger.py`**

```python
import uuid
import time
import json
import os
from agents.db import get_connection, DB_PATH


def write_run(entry: dict):
    conn = get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO runs (run_id, agent, trigger, triggered_at, task, status,
                              tokens_input, tokens_output, cost_usd, duration_seconds,
                              linear_ticket, output)
            VALUES (:run_id, :agent, :trigger, :triggered_at, :task, :status,
                    :tokens_input, :tokens_output, :cost_usd, :duration_seconds,
                    :linear_ticket, :output)
            """,
            {
                "run_id": entry.get("run_id") or str(uuid.uuid4()),
                "agent": entry["agent"],
                "trigger": entry["trigger"],
                "triggered_at": entry.get("triggered_at") or int(time.time()),
                "task": entry.get("task"),
                "status": entry["status"],
                "tokens_input": entry.get("tokens_input"),
                "tokens_output": entry.get("tokens_output"),
                "cost_usd": entry.get("cost_usd"),
                "duration_seconds": entry.get("duration_seconds"),
                "linear_ticket": entry.get("linear_ticket"),
                "output": json.dumps(entry["output"]) if entry.get("output") else None,
            },
        )
    conn.close()


def get_recent_runs(n: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY triggered_at DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def export_to_drive():
    import datetime
    from agents.drive_client import upload_backup

    backup_folder_id = os.environ["DRIVE_BACKUP_FOLDER_ID"]
    name = f"logs-backup-{datetime.date.today().isoformat()}.db"
    upload_backup(backup_folder_id, name, str(DB_PATH))
```

- [ ] **Step 4: Run tests — expect all to pass**

```bash
pytest tests/test_logger.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add agents/logger.py tests/test_logger.py
git commit -m "feat: run logger with SQLite persistence"
```

---

## Task 5: Claude Client

**Files:**
- Create: `agents/claude_client.py`

No unit tests — requires live API key. Tested via smoke test in Task 12.

- [ ] **Step 1: Write `agents/claude_client.py`**

```python
import os
import time
import anthropic


class ClaudeAPIError(Exception):
    pass


_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def complete(
    system_prompt: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 1024,
) -> str:
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
            return response.content[0].text
        except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
            last_error = e
            time.sleep(2**attempt)
        except anthropic.APIError as e:
            raise ClaudeAPIError(f"Claude API error: {e}") from e

    raise ClaudeAPIError(f"Claude API failed after 3 attempts: {last_error}") from last_error
```

- [ ] **Step 2: Commit**

```bash
git add agents/claude_client.py
git commit -m "feat: Claude API client with exponential backoff retry"
```

---

## Task 6: Drive Client

**Files:**
- Create: `agents/drive_client.py`

No unit tests — requires live service account credentials. Tested via smoke test in Task 12.

- [ ] **Step 1: Write `agents/drive_client.py`**

```python
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDENTIALS_PATH"],
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)


def create_file(folder_id: str, name: str, content: str) -> str:
    """Creates a plain-text file in Drive. Returns the new file ID."""
    service = _get_service()
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return file["id"]


def upload_backup(folder_id: str, name: str, file_path: str):
    """Uploads a binary file (the SQLite DB) to Drive as a backup."""
    service = _get_service()
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype="application/octet-stream")
    service.files().create(body=metadata, media_body=media).execute()
```

- [ ] **Step 2: Commit**

```bash
git add agents/drive_client.py
git commit -m "feat: Google Drive client for meal plan upload and DB backup"
```

---

## Task 7: PA System Prompt

**Files:**
- Create: `agents/pa/system-prompt.md`

- [ ] **Step 1: Write `agents/pa/system-prompt.md`**

```markdown
# Personal Assistant

You are a warm, concise personal assistant for Sam. You help with life tasks, answer questions, and assist with infant nutrition and meal planning over Telegram.

## Core Constraints

- All recipes and food suggestions must be **vegan** — no meat, fish, dairy, or eggs under any circumstances
- All nutrition advice must be age-appropriate for an infant — never suggest anything unsafe for the child's age (provided in context)
- Keep responses conversational and appropriately brief for a chat interface

## Meal Plan Format

When generating a meal plan, produce exactly **3 recipes** unless the user explicitly requests more. Format:

```
### [Recipe Name]
**Description:** [1-2 sentences — what it is and why it's good for the child]
**Ingredients:** [brief list]
**Preparation:** [2-3 sentences]
```

Follow all recipes with:

```
## Ingredients Needed
[Deduplicated ingredient list grouped by category: Produce / Grains & Legumes / Pantry / Other]
```

Recipes must be:
- Suitable for the child's current age
- Vegan
- Different from any recipes listed as recently used (variety)
- Not on the disliked list (never include these)
- Inspired by but not duplicating the favorites list (lean toward similar styles)

## Research Requests

When a message starts with `[RESEARCH REQUEST]`, provide a thorough summary covering key findings, any trade-offs or options, and a clear recommendation. Aim for 2-4 concise paragraphs.

## Remembering Recipes

When the user expresses that a recipe was a hit, loved, or a favorite — acknowledge it warmly ("Great, I'll remember that!"). When they express that something was disliked or won't be repeated — acknowledge with empathy ("Got it, I'll keep that off the list."). These signals will be logged automatically.

## Updating Preferences

If Sam asks to update the child's age, dietary notes, or other preferences, acknowledge the request and describe what should be updated. Note that you cannot directly modify settings — Sam should update them manually or you can acknowledge what you've heard for the memory summary.
```

- [ ] **Step 2: Commit**

```bash
git add agents/pa/system-prompt.md
git commit -m "feat: PA system prompt"
```

---

## Task 8: PA Agent — Signal Tests + Implementation

**Files:**
- Create: `tests/test_pa_signals.py`
- Create: `agents/pa/agent.py`

- [ ] **Step 1: Write `tests/test_pa_signals.py`**

```python
from agents.pa.agent import detect_signals


def test_positive_signal_detected():
    has_pos, has_neg = detect_signals("He loved the lentil soup!")
    assert has_pos is True
    assert has_neg is False


def test_negative_signal_detected():
    has_pos, has_neg = detect_signals("He didn't like the tofu scramble")
    assert has_pos is False
    assert has_neg is True


def test_no_signal_neutral_message():
    has_pos, has_neg = detect_signals("What should we have for dinner?")
    assert has_pos is False
    assert has_neg is False


def test_positive_signal_case_insensitive():
    has_pos, _ = detect_signals("That recipe was a HIT")
    assert has_pos is True


def test_negative_signal_case_insensitive():
    _, has_neg = detect_signals("He HATED the spinach puree")
    assert has_neg is True


def test_both_signals_simultaneously():
    has_pos, has_neg = detect_signals(
        "He loved the pasta but won't eat the spinach puree"
    )
    assert has_pos is True
    assert has_neg is True


def test_favorite_keyword():
    has_pos, _ = detect_signals("That's his favorite recipe so far")
    assert has_pos is True


def test_avoid_keyword():
    _, has_neg = detect_signals("Let's avoid that one in future")
    assert has_neg is True
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_pa_signals.py -v
```

Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Write `agents/pa/agent.py`**

```python
import os
import time
import uuid
import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

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
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def _get_favorites() -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT recipe_name FROM favorites ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [r["recipe_name"] for r in rows]


def _get_disliked() -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT recipe_name FROM disliked ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [r["recipe_name"] for r in rows]


def _get_recent_meal_plans(weeks: int = 4) -> list[str]:
    since = int(time.time()) - (weeks * 7 * 24 * 60 * 60)
    conn = get_connection()
    rows = conn.execute(
        "SELECT output FROM runs WHERE agent = 'pa' AND task = 'meal_plan' "
        "AND triggered_at > ? ORDER BY triggered_at DESC",
        (since,),
    ).fetchall()
    conn.close()
    return [r["output"] for r in rows if r["output"]]


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


def _save_recipe_signal(message: str, signal_type: str):
    recipe_name = _extract_recipe_name(message, signal_type)
    if not recipe_name:
        return
    table = "favorites" if signal_type == "positive" else "disliked"
    conn = get_connection()
    with conn:
        conn.execute(
            f"INSERT INTO {table} (recipe_name, notes, added_at) VALUES (?, ?, ?)",
            (recipe_name, message[:200], int(time.time())),
        )
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
    context = context_manager.get_context(chat_id, "pa")

    system_prompt = _load_system_prompt()
    if memory:
        system_prompt = f"{system_prompt}\n\n## Memory\n{memory}"

    messages = context + [{"role": "user", "content": message}]

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
        _save_recipe_signal(message, "positive")
    if has_negative:
        _save_recipe_signal(message, "negative")

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

def _allowed(update: Update) -> bool:
    return update.effective_user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])


async def _handle_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    msg = await update.message.reply_text("🟦 PA · Working on your meal plan…")
    try:
        meal_plan_job()
    except Exception as e:
        await msg.edit_text(f"🟦 PA · Meal plan failed: {e}")


async def _handle_research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text(
            "🟦 PA · Please provide a topic: /research [topic]"
        )
        return
    chat_id = str(update.effective_chat.id)
    response = run(f"[RESEARCH REQUEST] {topic}", chat_id)
    await update.message.reply_text(f"🟦 PA · {response}")


async def _handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    chat_id = str(update.effective_chat.id)
    context_manager.clear_context(chat_id, "pa")
    await update.message.reply_text("🟦 PA · Conversation context cleared.")


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    chat_id = str(update.effective_chat.id)
    response = run(update.message.text, chat_id)
    await update.message.reply_text(f"🟦 PA · {response}")


def register_handlers(app: Application):
    app.add_handler(CommandHandler("meal", _handle_meal))
    app.add_handler(CommandHandler("research", _handle_research))
    app.add_handler(CommandHandler("clear", _handle_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
```

- [ ] **Step 4: Run signal tests — expect all to pass**

```bash
pytest tests/test_pa_signals.py -v
```

Expected: 8 tests PASSED.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: All tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add agents/pa/agent.py tests/test_pa_signals.py
git commit -m "feat: PA agent with meal plan, conversation, memory update, and signal detection"
```

---

## Task 9: Telegram Bot

**Files:**
- Create: `bot.py`

- [ ] **Step 1: Write `bot.py`**

```python
import os
import logging
from dotenv import load_dotenv

load_dotenv("/home/pi/.env")

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
    return update.effective_user.id == int(os.environ["ALLOWED_TELEGRAM_USER_ID"])


async def handle_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    n = int(context.args[0]) if context.args else 5
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
    await update.message.reply_text("\n".join(lines))


def main():
    init_db()
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("logs", handle_logs))
    pa.register_handlers(app)
    app.run_polling()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add bot.py
git commit -m "feat: Telegram bot with PA handlers and /logs command"
```

---

## Task 10: Scheduler

**Files:**
- Create: `scheduler.py`

- [ ] **Step 1: Write `scheduler.py`**

```python
import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv("/home/pi/.env")

from apscheduler.schedulers.blocking import BlockingScheduler
import telegram

from agents.db import init_db
from agents import logger
import agents.pa.agent as pa

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

scheduler = BlockingScheduler()


def _alert(job_name: str, error: Exception):
    bot = telegram.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    asyncio.run(
        bot.send_message(
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
            text=f"⚠️ Scheduled job failed: {job_name}\n{error}",
        )
    )


def _run_job(name: str, fn):
    try:
        fn()
    except Exception as e:
        logging.error("Job %s failed: %s", name, e)
        try:
            _alert(name, e)
        except Exception:
            pass
        raise


@scheduler.scheduled_job("cron", day_of_week="fri", hour=8, minute=0)
def meal_plan():
    _run_job("meal_plan", pa.meal_plan_job)


@scheduler.scheduled_job("cron", day_of_week="sun", hour=0, minute=0)
def memory_update():
    _run_job("memory_update", pa.update_memory_summary)


@scheduler.scheduled_job("cron", hour=2, minute=0)
def drive_backup():
    _run_job("drive_backup", logger.export_to_drive)


if __name__ == "__main__":
    init_db()
    scheduler.start()
```

- [ ] **Step 2: Commit**

```bash
git add scheduler.py
git commit -m "feat: APScheduler with meal plan, memory update, and Drive backup jobs"
```

---

## Task 11: Systemd Unit Files

**Files:**
- Create: `deploy/bot.service`
- Create: `deploy/scheduler.service`

- [ ] **Step 1: Write `deploy/bot.service`**

```ini
[Unit]
Description=Personal Team Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/personal-team
EnvironmentFile=/home/pi/.env
ExecStart=/home/pi/personal-team/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `deploy/scheduler.service`**

```ini
[Unit]
Description=Personal Team Scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/personal-team
EnvironmentFile=/home/pi/.env
ExecStart=/home/pi/personal-team/.venv/bin/python scheduler.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Commit**

```bash
git add deploy/bot.service deploy/scheduler.service
git commit -m "feat: systemd unit files for bot and scheduler"
```

---

## Task 12: Pi Bootstrap Script

**Files:**
- Create: `deploy/setup.sh`

- [ ] **Step 1: Write `deploy/setup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/pi/personal-team"
ENV_FILE="/home/pi/.env"
CREDS_DIR="/home/pi/.config/personal-team"
CREDS_FILE="$CREDS_DIR/drive-credentials.json"

echo "=== Personal Team Pi Setup ==="
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/9] Installing system packages..."
sudo apt update -qq
sudo apt install -y python3.11 python3.11-venv git sqlite3 fail2ban curl

# ── 2. uv ─────────────────────────────────────────────────────────────────────
echo "[2/9] Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# ── 3. Clone repo ─────────────────────────────────────────────────────────────
echo "[3/9] Cloning repository..."
if [ ! -d "$REPO_DIR" ]; then
    read -rp "GitHub repo URL (e.g. https://github.com/you/personal-team.git): " REPO_URL
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# ── 4. Python environment ─────────────────────────────────────────────────────
echo "[4/9] Creating virtualenv and installing dependencies..."
uv venv .venv
uv pip install -r requirements.txt

# ── 5. Environment variables ──────────────────────────────────────────────────
echo "[5/9] Configuring environment variables..."
echo "Enter each value when prompted (leave blank to skip and set manually later):"

collect_var() {
    local key=$1
    local prompt=$2
    read -rp "  $prompt: " val
    echo "$key=$val"
}

{
    collect_var ANTHROPIC_API_KEY        "Anthropic API key"
    collect_var TELEGRAM_BOT_TOKEN       "Telegram bot token"
    collect_var ALLOWED_TELEGRAM_USER_ID "Your Telegram user ID"
    collect_var TELEGRAM_CHAT_ID         "Your Telegram chat ID with the bot"
    collect_var DRIVE_MEAL_PLANS_FOLDER_ID "Google Drive meal plans folder ID"
    collect_var DRIVE_BACKUP_FOLDER_ID    "Google Drive backup folder ID"
    echo "GOOGLE_CREDENTIALS_PATH=$CREDS_FILE"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "  Written to $ENV_FILE"

# ── 6. Drive service account credentials ─────────────────────────────────────
echo "[6/9] Setting up Google Drive credentials..."
mkdir -p "$CREDS_DIR"
echo "Paste your Drive service account JSON below, then press Enter and Ctrl+D:"
cat > "$CREDS_FILE"
chmod 600 "$CREDS_FILE"
echo "  Written to $CREDS_FILE"

# ── 7. SSH hardening ──────────────────────────────────────────────────────────
_harden_ssh() {
    sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
    sudo sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
    grep -q "^AllowUsers" /etc/ssh/sshd_config || echo "AllowUsers pi" | sudo tee -a /etc/ssh/sshd_config
    sudo systemctl restart sshd
    echo "  SSH hardened: password auth disabled, AllowUsers pi set."
}

echo "[7/9] SSH hardening..."
if [ ! -f "$HOME/.ssh/authorized_keys" ] || [ ! -s "$HOME/.ssh/authorized_keys" ]; then
    echo ""
    echo "  ⚠️  No SSH public key found in ~/.ssh/authorized_keys"
    echo "  You must add your SSH public key before disabling password auth."
    echo "  From your local machine, run:"
    echo "    ssh-copy-id pi@<pi-ip-address>"
    echo ""
    read -rp "  Have you added your SSH key? (yes/no): " KEY_CONFIRMED
    if [ "$KEY_CONFIRMED" != "yes" ]; then
        echo "  Skipping SSH hardening. Re-run setup.sh after adding your SSH key."
    else
        _harden_ssh
    fi
else
    _harden_ssh
fi

# ── 8. fail2ban ───────────────────────────────────────────────────────────────
echo "[8/9] Configuring fail2ban..."
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
echo "  fail2ban active."

# ── 9. Tailscale ─────────────────────────────────────────────────────────────
echo "[9/9] Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
echo "  Tailscale up. Authenticate in the browser if prompted."

# ── systemd services ──────────────────────────────────────────────────────────
echo ""
echo "=== Installing systemd services ==="
sudo cp deploy/bot.service /etc/systemd/system/personal-team-bot.service
sudo cp deploy/scheduler.service /etc/systemd/system/personal-team-scheduler.service
sudo systemctl daemon-reload
sudo systemctl enable personal-team-bot personal-team-scheduler
sudo systemctl start personal-team-bot personal-team-scheduler

# ── Initialise database ───────────────────────────────────────────────────────
echo "Initialising database..."
.venv/bin/python -c "from agents.db import init_db; init_db(); print('Database ready.')"

# ── Smoke test ────────────────────────────────────────────────────────────────
echo ""
echo "=== Smoke test ==="
echo "Sending test Telegram message..."
source "$ENV_FILE"
.venv/bin/python - <<'PYEOF'
import os, asyncio, telegram
from dotenv import load_dotenv
load_dotenv("/home/pi/.env")
async def send():
    bot = telegram.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        text="✅ Personal Team bot is live on the Pi!"
    )
asyncio.run(send())
PYEOF

echo ""
echo "=== Setup complete ==="
echo "Services running:"
sudo systemctl status personal-team-bot --no-pager -l | head -5
sudo systemctl status personal-team-scheduler --no-pager -l | head -5
echo ""
echo "To deploy updates:"
echo "  cd $REPO_DIR && git pull && sudo systemctl restart personal-team-bot personal-team-scheduler"
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x deploy/setup.sh
git add deploy/setup.sh
git commit -m "feat: Pi bootstrap script with SSH hardening, Tailscale, and systemd setup"
```

---

## Task 13: Final Check

- [ ] **Step 1: Run full test suite — all should pass**

```bash
pytest -v
```

Expected: All tests PASSED with no warnings about missing modules.

- [ ] **Step 2: Verify no secrets in the repo**

```bash
git log --oneline
git diff HEAD~1 HEAD --name-only
```

Confirm: no `.env`, no `drive-credentials.json`, no API keys in any committed file.

- [ ] **Step 3: Confirm `.gitignore` covers sensitive paths**

```bash
echo "test_key=secret" > .env && git status
```

Expected: `.env` shows as untracked but NOT as a new file to add — it should appear as ignored.

```bash
rm .env
```

- [ ] **Step 4: Final commit if anything remains staged**

```bash
git status
```

If clean: done. If anything unstaged: add and commit with appropriate message.
