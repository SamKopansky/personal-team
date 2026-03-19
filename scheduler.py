import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

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
            text=f"⚠️ Scheduled job failed: {job_name}. Check server logs.",
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
