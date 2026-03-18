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
        "ORDER BY timestamp DESC, id DESC LIMIT ?",
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
