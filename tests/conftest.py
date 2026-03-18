import pytest
from agents.db import init_db


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("agents.db.DB_PATH", db_path)
    init_db()
    yield
