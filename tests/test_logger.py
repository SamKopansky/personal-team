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
