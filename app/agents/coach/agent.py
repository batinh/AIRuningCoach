import os
import json
import logging
import pytz
from datetime import datetime
import google.generativeai as genai
from app.core.notification import send_telegram_msg
from app.core.database import save_message, load_history_for_gemini, clear_history
from app.agents.coach.strava_client import StravaClient
from app.agents.coach.utils import calculate_trimp, calculate_acwr

# Configure logging
logger = logging.getLogger(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def analyze_run_with_gemini(activity_id: str, activity_name: str, csv_data: str, meta_data: dict, config: dict):
    logger.info(f"[COACH AGENT] Analyzing run: {activity_name} (ID: {activity_id})")

    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(tz)
    
    # 1. DYNAMIC GOAL & PHASE MANAGEMENT
    race_date_str = config.get("race_date", "")
    current_goal = config.get("current_goal", "Duy trì thể lực (Maintenance)")
    
    if race_date_str:
        try:
            race_date = datetime.strptime(race_date_str, "%Y-%m-%d").replace(tzinfo=tz)
            days_to_race = (race_date - now).days
            weeks_to_race = max(0, days_to_race // 7)
            
            if weeks_to_race <= 2: phase = "Tapering (Giảm tải, giữ điểm rơi)"
            elif weeks_to_race <= 6: phase = "Peak Training (Tích lũy tối đa)"
            else: phase = "Base/Build (Xây dựng nền tảng)"
            countdown_text = f"{weeks_to_race} weeks ({days_to_race} days) remaining to Race Day."
        except ValueError:
            phase = "Off-season / Maintenance"
            countdown_text = "Invalid race date format."
    else:
        phase = "Off-season / Base Building"
        countdown_text = f"No race scheduled. Current Focus: {current_goal}."

    # 2. SCIENTIFIC LOAD TRACKING (TRIMP & ACWR)
    duration_min = meta_data.get("moving_time", 0) / 60
    avg_hr = meta_data.get("average_heartrate", 0)
    max_hr = int(config.get("max_hr", 185))
    rest_hr = int(config.get("rest_hr", 55))
    
    # Calculate TRIMP for this specific run
    trimp_data = calculate_trimp(duration_min, avg_hr, max_hr, rest_hr)
    
    # Calculate ACWR (Acute vs Chronic)
    acute_load_7d = 0.0
    chronic_load_28d = 0.0
    recent_log = "No recent data available."
    
    try:
        client = StravaClient()
        recent_activities = client.get_recent_activities(limit=20)
        
        # Calculate Acute Load (Last 7 days distance)
        for act in recent_activities:
            if act.get('type') in ['Run', 'TrailRun', 'VirtualRun']:
                act_date = datetime.strptime(act.get('start_date_local')[:10], "%Y-%m-%d").replace(tzinfo=tz)
                if (now - act_date).days <= 7:
                    acute_load_7d += (act.get('distance', 0) / 1000)

        # Build recent log for AI context
        recent_log = "\n".join([
            f"- {act.get('start_date_local')[:10]}: {act.get('name')} | {act.get('distance', 0)/1000:.1f}km" 
            for act in recent_activities[:5] if act.get('type') in ['Run', 'TrailRun']
        ])
    except Exception as e:
        logger.error(f"[AGENT] Failed to fetch recent activities for ACWR: {e}")

    # Fetch Chronic Load from harvest file
    if os.path.exists("data/athlete_stats.json"):
        with open("data/athlete_stats.json", "r") as f:
            s = json.load(f)
            chronic_load_28d = s.get('recent_run_totals', 0)

    acwr_data = calculate_acwr(acute_load_7d, chronic_load_28d)

    # 3. BUILD PROMPT CONTEXT
    system_instruction = config.get("system_instruction", "You are an elite AI Running Coach.")
    user_profile = config.get("user_profile", "")
    
    science_context = f"""
    [TEMPORAL & PERIODIZATION CONTEXT]
    - System Current Time: {now.strftime('%Y-%m-%d %H:%M:%S')}
    - Target: {countdown_text}
    - Current Phase: {phase}
    
    [SPORTS SCIENCE METRICS (CRITICAL)]
    - TRIMP (This Run): {trimp_data['trimp']} -> Intensity: {trimp_data['intensity_level']}
    - Acute Load (Last 7 Days): {acute_load_7d:.1f} km
    - Chronic Load (Last 4 Weeks): {chronic_load_28d:.1f} km
    - ACWR Ratio: {acwr_data['acwr']} -> Status: {acwr_data['status']}
    *Rule:* If ACWR Status is 'Danger Zone', YOU MUST explicitly warn the runner to take a rest or recovery day next.

    [RECENT WORKOUTS LOG]
    {recent_log}
    """

    full_instruction = f"{system_instruction}\n\n[USER PHYSIOLOGY]\n{user_profile}\nMax HR: {max_hr} | Rest HR: {rest_hr}\n\n{science_context}"
    
    task_description = config.get("task_description", "Analyze this run.") 
    output_format = config.get("output_format", "Output in Plain Text.")
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")

    meta_text = f"[DEVICE] {meta_data.get('device_name', 'Unknown')}\n"
    if meta_data.get('splits'):
        meta_text += "\n".join([f"Km {s['km']}: {s['pace']:.2f} m/s | HR {int(s['hr'])}" for s in meta_data.get('splits', [])])

    try:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        history = load_history_for_gemini(chat_id, limit=50) if chat_id else []
        model = genai.GenerativeModel(model_name=current_model_name, system_instruction=full_instruction)
        chat_session = model.start_chat(history=history)
    except Exception as e:
        logger.error(f"Error initializing AI: {e}")
        return None

    prompt = f"""
    [ACTIVITY DATA] Name: {activity_name}
    [TASK] {task_description}
    [METADATA] {meta_text}
    [FORMAT] {output_format}
    [RAW CSV]
    {csv_data}
    """
    
    try:
        response = chat_session.send_message(prompt) 
        analysis_text = response.text
        if chat_id and analysis_text:
            save_message(str(chat_id), "model", f"[ANALYSIS] {activity_name}: {analysis_text}")
        return analysis_text
    except Exception as e:
        logger.error(f"Analysis Error: {e}")
        return None
def handle_telegram_chat(chat_id: str, text: str, config: dict):
    debug_mode = config.get("debug_mode", False)
    
    if text.strip().lower() in ["/clear", "/reset", "xóa nhớ"]:
        clear_history(chat_id)
        send_telegram_msg(chat_id, "🧹 Đã xóa bộ nhớ. Chúng ta bắt đầu lại nhé!")
        return

    # 1. NHẬN THỨC THỜI GIAN HIỆN TẠI & MỤC TIÊU
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(tz)
    now_str = now.strftime('%A, %Y-%m-%d %H:%M:%S')

    race_date_str = config.get("race_date", "")
    current_goal = config.get("current_goal", "Duy trì thể lực (Maintenance)")
    
    if race_date_str:
        try:
            race_date = datetime.strptime(race_date_str, "%Y-%m-%d").replace(tzinfo=tz)
            days_to_race = (race_date - now).days
            weeks_to_race = max(0, days_to_race // 7)
            
            if weeks_to_race <= 2: phase = "Tapering (Giảm tải, giữ điểm rơi)"
            elif weeks_to_race <= 6: phase = "Peak Training (Tích lũy tối đa)"
            else: phase = "Base/Build (Xây dựng nền tảng)"
            countdown_text = f"{weeks_to_race} weeks ({days_to_race} days) remaining to Race Day."
        except ValueError:
            phase = "Off-season / Maintenance"
            countdown_text = "Invalid race date format."
    else:
        phase = "Off-season / Base Building"
        countdown_text = f"No race scheduled. Current Focus: {current_goal}."

    # 2. LẤY LỊCH SỬ CHẠY THỰC TẾ GẦN NHẤT (Tránh AI bị mù mờ)
    recent_log = "No recent data available."
    try:
        client = StravaClient()
        recent_activities = client.get_recent_activities(limit=5)
        recent_log = "\n".join([
            f"- Ngày: {act.get('start_date_local')[:10]} | Tên: {act.get('name')} | Cự ly: {act.get('distance', 0)/1000:.1f}km" 
            for act in recent_activities if act.get('type') in ['Run', 'TrailRun', 'VirtualRun']
        ])
    except Exception as e:
        logger.error(f"[TELEGRAM] Failed to fetch recent activities: {e}")

    # 3. LẤY TỔNG STATS
    dynamic_stats = ""
    if os.path.exists("data/athlete_stats.json"):
        try:
            with open("data/athlete_stats.json", "r") as f:
                s = json.load(f)
                dynamic_stats = f"\n[STATS TỔNG QUAN]: 4 tuần qua = {s.get('recent_run_totals', 0):.1f}km | Từ đầu năm = {s.get('ytd_run_totals', 0):.1f}km"
        except: pass

    # 4. ĐÓNG GÓI NHÂN CÁCH VÀ NGỮ CẢNH CHUẨN
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")

    full_persona = f"""
    {system_instruction}
    
    [TEMPORAL & PERIODIZATION CONTEXT]
    - System Current Time: {now_str}
    - Target: {countdown_text}
    - Current Phase: {phase}
    
    [RECENT WORKOUTS LOG (LỊCH SỬ CHẠY GẦN NHẤT)]
    Đây là dữ liệu CHÍNH XÁC từ hệ thống. Hãy đối chiếu thời gian hiện tại ({now_str}) với danh sách này để biết hôm nay/hôm qua user đã chạy gì, từ đó đưa ra lời khuyên cho ngày mai:
    {recent_log}
    
    {dynamic_stats}
    
    [USER PROFILE]
    {user_profile}
    
    [INSTRUCTION]
    - You are chatting directly with the user via Telegram.
    - Always consider the 'System Current Time' and 'Recent Workouts Log' to answer contextually (e.g., don't suggest a long run tomorrow if they just did 21km today).
    - Keep responses concise, helpful, and friendly.
    """

    try:
        current_history = load_history_for_gemini(chat_id, limit=50)
        model = genai.GenerativeModel(model_name=current_model_name, system_instruction=full_persona)
        
        chat_session = model.start_chat(history=current_history)
        response = chat_session.send_message(text)
        reply_text = response.text

        save_message(chat_id, "user", text)
        save_message(chat_id, "model", reply_text)

        send_telegram_msg(chat_id, reply_text)
        
    except Exception as e:
        logger.error(f"[TELEGRAM] Chat Error: {e}")
        send_telegram_msg(chat_id, "⚠️ Coach Dyno đang bị 'chuột rút' hoặc quá tải. Thử /clear xem sao!")