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
    """Gửi bản tin tóm tắt buổi sáng qua Telegram"""
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        stats = {}
        # Đọc dữ liệu Strava đã được harvest_data thu thập
        if os.path.exists("data/athlete_stats.json"):
            try:
                with open("data/athlete_stats.json", "r") as f:
                    stats = json.load(f)
            except Exception as e:
                logger.error(f"[SCHEDULER] Failed to read stats: {e}")
        
        ytd_km = stats.get('ytd_run_totals', 0)
        recent_km = stats.get('recent_run_totals', 0)
        
        # Format tin nhắn tiếng Việt chuẩn Markdown
        msg = (
            f"☀️ **CHÀO BUỔI SÁNG DYNO!**\n"
            f"📅 Hôm nay là: {datetime.now(TZ_VN).strftime('%A, %d/%m')}\n"
            f"--------------------------------\n"
            f"📊 **Tổng kết phong độ:**\n"
            f"▪️ Tích lũy năm nay: `{ytd_km:.1f} km`\n"
            f"▪️ Volume 4 tuần: `{recent_km:.1f} km`\n\n"
            f"🔥 *Chỉ còn 5 tuần nữa là đến Race. Đừng quên bài chạy hôm nay nhé!*\n"
            f"💡 *Gõ /sync để cập nhật dữ liệu nếu cậu vừa chạy xong.*"
        )
        send_telegram_msg(chat_id, msg)
        logger.info("[SCHEDULER] Sent Morning Briefing.")

async def task_auto_harvest():
    """Tự động đồng bộ Strava mỗi 6 tiếng"""
    logger.info("[SCHEDULER] Auto-harvesting...")
    harvest_data()

def start_scheduler():
    # Chạy lúc 6:00 sáng mỗi ngày
    scheduler.add_job(task_morning_briefing, CronTrigger(hour=6, minute=0, timezone=TZ_VN))
    # Chạy auto sync Strava 4 lần/ngày
    scheduler.add_job(task_auto_harvest, CronTrigger(hour='0,6,12,18', minute=15, timezone=TZ_VN))
    
    scheduler.start()