import os
import json
from dotenv import load_dotenv
from tools.strava_client import StravaClient
from tools.memory_db import save_message, init_db

# Load biến môi trường
load_dotenv()

def harvest_data():
    print("🚀 Đang khởi tạo quá trình thu hoạch dữ liệu Strava...")
    init_db() # Đảm bảo database đã sẵn sàng [cite: 63]
    
    # Khởi tạo Strava Client [cite: 142]
    # Lưu ý: Class StravaClient của bạn lấy thông tin từ .env trong hàm __init__ [cite: 142]
    strava = StravaClient()
    
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    athlete_id = os.getenv("STRAVA_ATHLETE_ID")

    if not chat_id or not athlete_id:
        print("❌ Lỗi: Thiếu TELEGRAM_CHAT_ID hoặc STRAVA_ATHLETE_ID trong .env")
        return

    # 1. Thu hoạch Athlete Stats (Tổng tích lũy) [cite: 154]
    print(f"📊 Đang lấy Stats cho Athlete ID: {athlete_id}...")
    stats = strava.get_athlete_stats(athlete_id)
    if stats:
        with open("data/athlete_stats.json", "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=4)
        print(f"✅ Đã cập nhật Stats: Tổng năm nay {stats['ytd_run_totals']:.1f} km")

    # 2. Thu hoạch 10 bài chạy gần nhất [cite: 157]
    print("🏃 Đang lấy lịch sử 10 bài chạy gần nhất...")
    activities = strava.get_recent_activities(limit=10)
    
    # Nạp vào DB theo thứ tự từ cũ đến mới
    for act in reversed(activities):
        if act.get('type') in ['Run', 'TrailRun', 'VirtualRun']:
            distance_km = act['distance'] / 1000
            # Tính pace (phút/km)
            pace_min_km = (act['moving_time'] / 60) / distance_km
            
            summary = (
                f"[HISTORICAL RUN] {act['start_date_local'][:10]} | {act['name']}\n"
                f"📏 Quãng đường: {distance_km:.2f} km\n"
                f"⚡ Pace: {int(pace_min_km)}:{int((pace_min_km%1)*60):02d} min/km"
            )
            
            # Lưu vào bộ nhớ hội thoại [cite: 138]
            save_message(str(chat_id), "model", summary)
            print(f"   + Đã nạp bài: {act['name']}")

    print("🏁 Hoàn thành! Agent của bạn đã được nạp đầy đủ lịch sử.")

if __name__ == "__main__":
    harvest_data()