import time

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
