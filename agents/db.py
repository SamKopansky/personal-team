import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "logs.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = get_connection()
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

        CREATE INDEX IF NOT EXISTS idx_messages_chat_agent_ts
            ON messages(chat_id, agent, timestamp DESC, id DESC);

        CREATE INDEX IF NOT EXISTS idx_messages_agent_ts
            ON messages(agent, timestamp);

        CREATE INDEX IF NOT EXISTS idx_runs_triggered_at
            ON runs(triggered_at DESC);

        CREATE INDEX IF NOT EXISTS idx_runs_agent_task_ts
            ON runs(agent, task, triggered_at DESC);
    """)
    conn.close()
