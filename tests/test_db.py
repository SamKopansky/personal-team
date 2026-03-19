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
