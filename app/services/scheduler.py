from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import os
import json
import logging
from datetime import datetime
from app.core.notification import send_telegram_msg
from app.agents.coach.harvest import harvest_data

logger = logging.getLogger("AI_COACH")
TZ_VN = pytz.timezone('Asia/Ho_Chi_Minh')
scheduler = AsyncIOScheduler()

async def task_morning_briefing():
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        # ... Logic đọc stats và gửi tin nhắn (Copy từ main cũ) ...
        msg = f"☀️ Chào buổi sáng! (Refactored Scheduler)"
        send_telegram_msg(chat_id, msg)

async def task_auto_harvest():
    logger.info("[SCHEDULER] Auto-harvesting...")
    harvest_data()

def start_scheduler():
    scheduler.add_job(task_morning_briefing, CronTrigger(hour=6, minute=0, timezone=TZ_VN))
    scheduler.add_job(task_auto_harvest, CronTrigger(hour='0,6,12,18', minute=15, timezone=TZ_VN))
    scheduler.start()