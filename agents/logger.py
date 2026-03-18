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
