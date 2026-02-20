import os
import json
import logging
import asyncio
import io
import pandas as pd
from datetime import datetime, timedelta

from app.agents.coach.strava_client import StravaClient
from app.agents.coach.utils import calculate_trimp, calculate_efficiency_factor, analyze_decoupling
from app.core.config import load_config
from app.core.database import init_db, upsert_user, save_run_activity, save_message, get_db_connection
from app.core.notification import send_telegram_msg
from app.services.rag_memory import rag_db

logger = logging.getLogger("AI_COACH")

def harvest_data():
    """Luồng Auto-harvest chạy ngầm theo lịch Cron"""
    logger.info("[HARVEST] Starting Strava data harvest process...")
    init_db()
    strava_client = StravaClient()
    config = load_config()
    
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    athlete_id = os.getenv("STRAVA_ATHLETE_ID")

    if not chat_id or not athlete_id: return

    max_hr = int(config.get("max_hr", 185))
    rest_hr = int(config.get("rest_hr", 55))
    upsert_user(user_id=chat_id, name="Primary Runner", max_hr=max_hr, rest_hr=rest_hr)

    athlete_stats = strava_client.get_athlete_stats(athlete_id)
    if athlete_stats:
        os.makedirs("data", exist_ok=True)
        with open("data/athlete_stats.json", "w", encoding="utf-8") as file:
            json.dump(athlete_stats, file, indent=4)

    recent_activities = strava_client.get_recent_activities(limit=10)
    for activity in reversed(recent_activities):
        if activity.get('type') in ['Run', 'TrailRun', 'VirtualRun']:
            dist_km = activity.get('distance', 0) / 1000
            moving_min = activity.get('moving_time', 0) / 60
            avg_hr = activity.get('average_heartrate', 0)
            trimp_data = calculate_trimp(moving_min, avg_hr, max_hr, rest_hr)
            
            activity_data = {
                'activity_id': str(activity.get('id')),
                'name': activity.get('name', 'Unknown Run'),
                'start_date': activity.get('start_date_local'),
                'distance_km': round(dist_km, 2),
                'moving_time_min': round(moving_min, 2),
                'avg_hr': int(avg_hr),
                'max_hr': int(activity.get('max_heartrate', 0)),
                'suffer_score': int(activity.get('suffer_score', 0) or 0),
                'trimp_score': trimp_data.get('trimp', 0.0)
            }
            save_run_activity(user_id=chat_id, activity_data=activity_data)
    logger.info("[HARVEST] Cron Auto-Harvest complete.")

async def execute_manual_sync(chat_id: str, limit: int = 3, days_back: int = None):
    """Luồng đồng bộ lịch sử chạy tay: Bảo vệ Quota, cấy Ký ức Python trực tiếp."""
    logger.info(f"[SYNC] Bắt đầu đồng bộ thủ công. Limit: {limit}, Days back: {days_back}")
    send_telegram_msg(chat_id, f"⏳ Đang thu hoạch dữ liệu Strava ({'30 ngày qua' if days_back else f'{limit} bài gần nhất'})...")
    
    init_db()
    strava_client = StravaClient()
    config = load_config()
    max_hr = int(config.get("max_hr", 185))
    rest_hr = int(config.get("rest_hr", 55))
    
    recent_activities = strava_client.get_recent_activities(limit=limit)
    target_activities = []
    
    if days_back:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        for act in recent_activities:
            try:
                act_date = datetime.strptime(act['start_date_local'][:10], "%Y-%m-%d")
                if act_date >= cutoff_date: target_activities.append(act)
            except Exception: target_activities.append(act)
    else: target_activities = recent_activities

    if not target_activities:
        send_telegram_msg(chat_id, "⚠️ Không tìm thấy bài chạy nào phù hợp.")
        return


    loaded_count = 0
    analyzed_count = 0
    for activity in reversed(target_activities):
        act_id = str(activity.get('id'))
        if activity.get('type') not in ['Run', 'TrailRun', 'VirtualRun']: continue

        # 1. Luôn tính toán và cập nhật SQLite (Lệnh REPLACE sẽ tự động chữa lành/ghi đè an toàn)
        dist_km = activity.get('distance', 0) / 1000
        moving_min = activity.get('moving_time', 0) / 60
        avg_hr = activity.get('average_heartrate', 0)
        trimp_data = calculate_trimp(moving_min, avg_hr, max_hr, rest_hr)
        
        activity_data = {
            'activity_id': act_id,
            'name': activity.get('name', 'Unknown Run'),
            'start_date': activity.get('start_date_local'),
            'distance_km': round(dist_km, 2),
            'moving_time_min': round(moving_min, 2),
            'avg_hr': int(avg_hr),
            'max_hr': int(activity.get('max_heartrate', 0)),
            'suffer_score': int(activity.get('suffer_score', 0) or 0),
            'trimp_score': trimp_data.get('trimp', 0.0)
        }
        save_run_activity(user_id=chat_id, activity_data=activity_data)
        loaded_count += 1
        
        # 2. CHỐT CHẶN MỚI: Hỏi thẳng ChromaDB xem ký ức đã có chưa?
        existing_memory = rag_db.collection.get(ids=[act_id])
        if existing_memory and existing_memory['ids']:
            logger.info(f"[SYNC] Bỏ qua RAG cho {act_id} vì Ký ức đã tồn tại trong não bộ.")
            continue # Nếu có rồi thì bỏ qua phần tính Streams bên dưới để tiết kiệm CPU
            
        # 3. Nạp Ký ức Python cho những bài chạy bị thiếu (như các bài bị lỗi 429 trước đây)
        logger.info(f"[SYNC] Đang vá lỗ hổng Ký ức cho bài chạy {act_id}...")
        act_name, csv_data, meta_data = strava_client.get_activity_data(act_id)
        ef_val, decoupling_val, cadence_avg, stride_avg = 0.0, 0.0, 0, 0.0
        pace_str = f"{int(moving_min/dist_km)}:{int(((moving_min/dist_km)%1)*60):02d}" if dist_km > 0 else "0:00"

        if csv_data:
            try:
                df = pd.read_csv(io.StringIO(csv_data))
                if not df.empty:
                    decoupling_val = analyze_decoupling(df)
                    ef_val = calculate_efficiency_factor(df['Velocity_m_s'].mean() * 60, df['HR_bpm'].mean())
                    
                    # [FIX BUG] Xử lý an toàn cho Cadence (Tránh lỗi NaN)
                    c_mean = df['Cadence_spm'].mean() if 'Cadence_spm' in df.columns else 0
                    cadence_avg = int(c_mean) if pd.notna(c_mean) else 0
                    
                    # [FIX BUG] Xử lý an toàn cho Stride
                    s_mean = df['Stride_m'].mean() if 'Stride_m' in df.columns else 0.0
                    stride_avg = round(s_mean, 2) if pd.notna(s_mean) else 0.0
            except Exception as e:
                logger.error(f"[SYNC] Lỗi phân tích Streams cho {act_id}: {e}")

        memory_content = (
            f"[HỒ SƠ BÀI CHẠY LỊCH SỬ]\n"
            f"- Cơ bản: Ngày {activity_data['start_date'][:10]}, '{act_name}'. Quãng đường {dist_km:.2f}km, thời gian {moving_min:.1f} phút.\n"
            f"- Tải trọng (Load): Tim TB {int(avg_hr)} bpm (Max {int(activity_data['max_hr'])}). TRIMP: {activity_data['trimp_score']} ({trimp_data.get('intensity_level')}).\n"
            f"- Hiệu suất (Performance): Pace TB {pace_str} min/km. Chỉ số hiệu quả (EF): {ef_val}. Độ trôi nhịp tim (Decoupling): {decoupling_val}%.\n"
            f"- Kỹ thuật (Form): Cadence {cadence_avg} spm, Sải chân {stride_avg} mét."
        )

        rag_db.memorize(
            doc_id=act_id,
            content=memory_content,
            domain="coach",
            extra_meta={"user_id": str(chat_id), "type": "historical_run"}
        )
        analyzed_count += 1
        await asyncio.sleep(1)

    send_telegram_msg(chat_id, f"🎉 **Hoàn tất Đồng bộ Lịch sử!**\nĐã bổ sung {loaded_count} bài chạy vào Cơ sở dữ liệu và cấy {analyzed_count} Gói Ký ức (EF, Decoupling, TRIMP) vào não bộ AI. Số liệu ACWR đã được cân bằng.")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    harvest_data()