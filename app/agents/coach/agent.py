import os
import json
import logging
import pytz
import uuid
import time
import re
from datetime import datetime

# Import thư viện SDK thế hệ mới của Google
from google import genai
from google.genai import types

from app.core.notification import send_telegram_msg
from app.core.database import (
    save_message, load_history_for_gemini, clear_history,
    get_training_loads, get_recent_runs_log, update_run_gcs_score
)
from app.agents.coach.utils import calculate_trimp, calculate_acwr
from app.services.rag_memory import rag_db

# Configure logging
logger = logging.getLogger("AI_COACH")
client = genai.Client()

# ==========================================
# 🧰 BỘ CÔNG CỤ (TOOLS) CHO AI AGENT
# ==========================================
# Ghi chú: Docstring (""") bên dưới cực kỳ quan trọng. 
# Gemini sẽ đọc nó để hiểu khi nào cần lấy công cụ nào ra dùng.

def check_training_status(user_id: str) -> str:
    """
    Kiểm tra chỉ số chấn thương (ACWR) và tải trọng tập luyện (TRIMP) hiện tại của vận động viên.
    Hãy gọi công cụ này khi user hỏi về tình trạng thể lực, mệt mỏi, mỏi cơ, hoặc cần tư vấn xem có nên chạy tiếp hay nghỉ ngơi.
    """
    logger.info(f"[TOOL-USE] 🤖 AI tự động gọi Tool: check_training_status cho User {user_id}")
    loads = get_training_loads(user_id)
    acwr_data = calculate_acwr(loads.get("acute_load_7d", 0), loads.get("chronic_load_28d", 0))
    return f"ACWR: {acwr_data['acwr']} ({acwr_data['status']}) | Acute Load 7d: {loads.get('acute_load_7d')} | Chronic Load 28d: {loads.get('chronic_load_28d')}"

def get_recent_workouts(user_id: str) -> str:
    """
    Lấy danh sách 5 bài tập chạy bộ gần nhất của vận động viên trên Strava.
    Hãy gọi công cụ này để biết trong những ngày qua user đã chạy quãng đường bao nhiêu, nhịp tim thế nào, pace ra sao.
    """
    logger.info(f"[TOOL-USE] 🤖 AI tự động gọi Tool: get_recent_workouts cho User {user_id}")
    return get_recent_runs_log(user_id, limit=5)

def search_long_term_memory(query: str) -> str:
    """
    Tìm kiếm trí nhớ dài hạn (ChromaDB) để lấy bối cảnh về các bài chạy cũ, lời khuyên quá khứ, hoặc chấn thương đã từng xảy ra.
    Hãy gọi công cụ này khi user nhắc đến chuyện tuần trước, tháng trước, hoặc cần so sánh hiện tại với quá khứ.
    """
    logger.info(f"[TOOL-USE] 🤖 AI tự động gọi Tool: search_long_term_memory với từ khóa '{query}'")
    try:
        results = rag_db.recall(query=query, domain="coach", n_results=3)
        if not results or not results.get('documents') or not results['documents'][0]:
            return "Không tìm thấy ký ức nào liên quan trong não bộ."
        docs = results['documents'][0]
        return "\n".join([f"- Ký ức: {doc}" for doc in docs])
    except Exception as e:
        return f"Lỗi truy xuất ký ức: {e}"

def get_total_run_stats(user_id: str) -> str:
    """
    Lấy thống kê tổng quãng đường chạy (km) của vận động viên (trong 4 tuần qua, năm nay, và toàn thời gian).
    Hãy gọi công cụ này khi user hỏi về tổng số km đã chạy.
    """
    logger.info(f"[TOOL-USE] 🤖 AI tự động gọi Tool: get_total_run_stats cho User {user_id}")
    try:
        with open("data/athlete_stats.json", "r") as f:
            stats = json.load(f)
        return f"Volume 4 tuần qua: {stats.get('recent_run_totals', 0):.1f} km | Năm nay (YTD): {stats.get('ytd_run_totals', 0):.1f} km"
    except Exception as e:
        return "Chưa có dữ liệu thống kê tổng km (Auto-Harvest chưa thu thập)."
# (Giữ lại hàm này cho luồng phân tích CSV tự động)
def get_rag_context(query: str, n_results: int = 2) -> str:
    try:
        results = rag_db.recall(query=query, domain="coach", n_results=n_results)
        if not results or not results.get('documents') or not results['documents'][0]:
            return "No relevant long-term memories found."
        docs = results['documents'][0]
        return "\n".join([f"- Ký ức: {doc}" for doc in docs])
    except Exception as e:
        return "Memory retrieval failed."

# ==========================================
# LUỒNG 1: PHÂN TÍCH BÀI CHẠY TỰ ĐỘNG (GIỮ NGUYÊN)
# ==========================================
def analyze_run_with_gemini(activity_id: str, activity_name: str, csv_data: str, meta_data: dict, config: dict):
    activity_id = str(activity_id) 
    logger.info(f"[COACH AGENT] Analyzing run: {activity_name} (ID: {activity_id})")

    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(tz)
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
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

    max_hr = int(config.get("max_hr", 185))
    rest_hr = int(config.get("rest_hr", 55))
    
    loads = get_training_loads(str(chat_id))
    acute_load_7d = loads.get("acute_load_7d", 0)
    chronic_load_28d = loads.get("chronic_load_28d", 0)
    acwr_data = calculate_acwr(acute_load_7d, chronic_load_28d)
    recent_log = get_recent_runs_log(str(chat_id), limit=5)
    long_term_memory = get_rag_context(query=f"Phân tích bài chạy {activity_name}", n_results=2)

    system_instruction = config.get("system_instruction", "You are an elite AI Running Coach.")
    user_profile = config.get("user_profile", "")
    
    science_context = f"""
    [TEMPORAL & PERIODIZATION CONTEXT]
    - System Current Time: {now.strftime('%Y-%m-%d %H:%M:%S')}
    - Target: {countdown_text}
    - Current Phase: {phase}
    
    [SPORTS SCIENCE METRICS (CRITICAL)]
    - Acute TRIMP Load: {acute_load_7d}
    - Chronic TRIMP Load: {chronic_load_28d}
    - ACWR Ratio: {acwr_data['acwr']} -> Status: {acwr_data['status']}
    *Rule:* If ACWR Status is 'Danger Zone', YOU MUST warn the runner to take a rest.

    [RECENT WORKOUTS LOG]
    {recent_log}
    
    [LONG-TERM MEMORY]
    {long_term_memory}
    """

    full_instruction = f"{system_instruction}\n\n[USER PHYSIOLOGY]\n{user_profile}\nMax HR: {max_hr} | Rest HR: {rest_hr}\n\n{science_context}"
    task_description = config.get("task_description", "Analyze this run.") 
    output_format = config.get("output_format", "Output in Plain Text.")
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")

    meta_text = f"[DEVICE] {meta_data.get('device_name', 'Unknown')}\n"
    if meta_data.get('splits'):
        meta_text += "\n".join([f"Km {s['km']}: {s['pace']:.2f} m/s | HR {int(s['hr'])}" for s in meta_data.get('splits', [])])

    try:
        raw_history = load_history_for_gemini(str(chat_id), limit=50) if chat_id else []
        formatted_history = [{"role": msg["role"], "parts": [{"text": msg["parts"][0]}]} for msg in raw_history]
        
        chat_session = client.chats.create(
            model=current_model_name,
            history=formatted_history,
            config=types.GenerateContentConfig(
                system_instruction=full_instruction,
                temperature=0.7
            )
        )
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

    if os.getenv("LOG_AI_PROMPTS", "False").lower() == "true":
        debug_prompt = prompt.replace(csv_data, f"<CSV_DATA_OMITTED_FOR_LOGS> ({len(csv_data)} bytes)")
        logger.info(f"\n{'='*20} [AI PROMPT: RUN ANALYSIS] {'='*20}\n[SYSTEM INSTRUCTION & RAG CONTEXT]:\n{full_instruction}\n\n[USER PROMPT]:\n{debug_prompt}\n{'='*65}\n")

    max_retries = 3
    analysis_text = None
    
    for attempt in range(max_retries):
        try:
            response = chat_session.send_message(prompt) 
            analysis_text = response.text
            
            gcs_pattern = r"(?:🎯|GOAL CONFIDENCE SCORE|GCS).*?[:\s](\d{1,3})%"
            gcs_match = re.search(gcs_pattern, analysis_text, re.IGNORECASE | re.UNICODE)
            
            if gcs_match:
                gcs_score = int(gcs_match.group(1))
                gcs_score = max(0, min(100, gcs_score))
                update_run_gcs_score(activity_id, gcs_score)
            break
        except Exception as api_err:
            if "429" in str(api_err):
                time.sleep(60)
            else:
                break

    if not analysis_text: return None

    try:
        if chat_id:
            save_message(str(chat_id), "model", f"[ANALYSIS] {activity_name}: {analysis_text}")
            memory_content = f"Sự kiện: VĐV chạy bài '{activity_name}' vào ngày {now.strftime('%Y-%m-%d')}.\nPhân tích:\n{analysis_text}"
            rag_db.memorize(
                doc_id=str(activity_id), 
                content=memory_content, 
                domain="coach", 
                extra_meta={"user_id": str(chat_id), "type": "run_analysis"}
            )
        return analysis_text
    except Exception as e:
        logger.error(f"Post-Analysis Save Error: {e}")
        return None

# ==========================================
# LUỒNG 2: AI AGENTIC CHAT (ĐÃ NÂNG CẤP TOOL-USE)
# ==========================================
def handle_telegram_chat(chat_id: str, text: str, config: dict):
    chat_id = str(chat_id)
    if text.strip().lower() in ["/clear", "/reset", "xóa nhớ"]:
        clear_history(chat_id)
        send_telegram_msg(chat_id, "🧹 Não bộ đã được làm sạch. Sẵn sàng nhận lệnh mới!")
        return

    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(tz)
    now_str = now.strftime('%A, %Y-%m-%d %H:%M:%S')

    race_date_str = config.get("race_date", "")
    current_goal = config.get("current_goal", "Duy trì thể lực")
    
    if race_date_str:
        try:
            race_date = datetime.strptime(race_date_str, "%Y-%m-%d").replace(tzinfo=tz)
            days_to_race = (race_date - now).days
            weeks_to_race = max(0, days_to_race // 7)
            phase = "Tapering" if weeks_to_race <= 2 else "Peak Training" if weeks_to_race <= 6 else "Base/Build"
            countdown_text = f"{weeks_to_race} weeks ({days_to_race} days) remaining."
        except ValueError:
            phase, countdown_text = "Off-season", "Invalid date."
    else:
        phase, countdown_text = "Off-season", f"Focus: {current_goal}"

    # ĐÓNG GÓI NHÂN CÁCH MỎNG (THIN PERSONA)
    # Loại bỏ hoàn toàn việc bắt Python truy xuất DB và nhồi vào đây.
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")

    full_persona = f"""
    {system_instruction}
    
    [CONTEXT]
    - System Time: {now_str}
    - Target: {countdown_text}
    - Current Phase: {phase}
    - User ID of the runner: {chat_id}
    
    [USER PROFILE]
    {user_profile}
    
    [CRITICAL INSTRUCTION FOR TOOL USE]
    - You are chatting with the user on Telegram.
    - USE TOOLS to fetch training status, recent workouts, or memory IF required.
    - If you use a tool, always pass the 'user_id' exactly as '{chat_id}'.
    - If you lack the tools to answer a specific part of the user's question, clearly explain that to the user. DO NOT return an empty response.
    """

    try:
        raw_history = load_history_for_gemini(chat_id, limit=30)
        formatted_history = [{"role": msg["role"], "parts": [{"text": msg["parts"][0]}]} for msg in raw_history]
        
        # CẤP 4 VŨ KHÍ (Thêm get_total_run_stats)
        ai_tools = [check_training_status, get_recent_workouts, search_long_term_memory, get_total_run_stats]

        chat_session = client.chats.create(
            model=current_model_name,
            history=formatted_history,
            config=types.GenerateContentConfig(
                system_instruction=full_persona,
                temperature=0.7,
                tools=ai_tools 
            )
        )
        
        # Nhờ tính năng AFC (Automatic Function Calling), lệnh send_message này
        # sẽ tự động gọi các hàm Python bên trên nếu AI thấy cần thiết, 
        # sau đó AI tự tổng hợp kết quả và trả về text cuối cùng.
        response = chat_session.send_message(text)
        # [FIX BUG] Bẫy lỗi an toàn cho NoneType
        if response.text:
            reply_text = response.text
        else:
            logger.error(f"[TELEGRAM] AI trả về kết quả Rỗng. Nguyên nhân có thể do kẹt Tool. Candidates: {response.candidates}")
            reply_text = "⚠️ Coach Dyno đang kiểm tra số liệu nhưng gặp trục trặc khi tổng hợp (Thiếu công cụ đo lường). Anh thử hỏi tách từng ý ra nhé!"

        save_message(chat_id, "user", text)
        save_message(chat_id, "model", reply_text)
        send_telegram_msg(chat_id, reply_text)
        
        # Bây giờ lệnh len() sẽ không bao giờ bị crash nữa
        if len(reply_text) > 100 and "⚠️" not in reply_text:
            doc_id = f"chat_{uuid.uuid4().hex[:8]}"
            rag_db.memorize(
                doc_id=doc_id, 
                content=f"Vào {now_str}, User: '{text}'. Coach: '{reply_text}'", 
                domain="coach", 
                extra_meta={"user_id": chat_id, "type": "chat_advice"}
            )
            
    except Exception as e:
        logger.error(f"[TELEGRAM] Chat Error: {e}")
        send_telegram_msg(chat_id, "⚠️ Coach Dyno đang bị 'chuột rút' (Lỗi Agent). Thử /clear xem sao!")