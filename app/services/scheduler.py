from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import os
import json
import logging
from datetime import datetime
from app.core.notification import send_telegram_msg
from app.agents.coach.harvest import harvest_data
from app.services.backup import perform_backup
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

# ... (Giữ nguyên các import và các hàm task_morning_briefing, task_auto_harvest, perform_backup) ...

from app.core.config import load_config

def setup_jobs():
    """Đọc cấu hình và thiết lập lịch chạy (có thể gọi lại để reload)"""
    config = load_config()
    sched_cfg = config.get("scheduler", {})
    
    # 1. Lịch Briefing (Mặc định 06:00)
    brief_time = sched_cfg.get("briefing_time", "06:00")
    try: bh, bm = map(int, brief_time.split(':'))
    except: bh, bm = 6, 0
    
    # 2. Lịch Backup (Mặc định 02:00)
    backup_time = sched_cfg.get("backup_time", "02:00")
    try: bkh, bkm = map(int, backup_time.split(':'))
    except: bkh, bkm = 2, 0
    
    # 3. Lịch Harvest (Mặc định chạy các khung giờ 0,6,12,18 phút 15)
    harv_hours = sched_cfg.get("harvest_hours", "0,6,12,18")
    harv_min = str(sched_cfg.get("harvest_minute", "15"))

    # replace_existing=True giúp đè lịch mới lên lịch cũ nếu cùng ID
    scheduler.add_job(task_morning_briefing, CronTrigger(hour=bh, minute=bm, timezone=TZ_VN), id='briefing', replace_existing=True)
    scheduler.add_job(perform_backup, CronTrigger(hour=bkh, minute=bkm, timezone=TZ_VN), id='backup', replace_existing=True)
    scheduler.add_job(task_auto_harvest, CronTrigger(hour=harv_hours, minute=harv_min, timezone=TZ_VN), id='harvest', replace_existing=True)
    
    logger.info(f"[SCHEDULER] Đã nạp lịch: Briefing({bh}:{bm}), Backup({bkh}:{bkm}), Harvest({harv_hours}h:{harv_min}m)")

def start_scheduler():
    """Khởi động bộ lập lịch lần đầu tiên"""
    setup_jobs()
    scheduler.start()

def reload_scheduler():
    """Gọi từ Admin UI để cập nhật lịch ngay lập tức"""
    setup_jobs()