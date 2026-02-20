import os
import json
import logging
import pytz
import uuid
import time
import re
from datetime import datetime

# [NEW] Import thư viện SDK thế hệ mới của Google
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

# [NEW] Khởi tạo Client kiểu mới
client = genai.Client()

def get_rag_context(query: str, n_results: int = 2) -> str:
    """Truy xuất các ký ức dài hạn có liên quan từ ChromaDB."""
    try:
        results = rag_db.recall(query=query, domain="coach", n_results=n_results)
        if not results or not results.get('documents') or not results['documents'][0]:
            return "No relevant long-term memories found."
        
        docs = results['documents'][0]
        memory_str = "\n".join([f"- Ký ức: {doc}" for doc in docs])
        return memory_str
    except Exception as e:
        logger.error(f"[RAG] Recall Error: {e}")
        return "Memory retrieval failed."

def analyze_run_with_gemini(activity_id: str, activity_name: str, csv_data: str, meta_data: dict, config: dict):
    # Đảm bảo activity_id luôn là string ngay từ đầu
    activity_id = str(activity_id) 
    logger.info(f"[COACH AGENT] Analyzing run: {activity_name} (ID: {activity_id})")

    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(tz)
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
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

    # 2. SCIENTIFIC LOAD TRACKING
    max_hr = int(config.get("max_hr", 185))
    rest_hr = int(config.get("rest_hr", 55))
    
    loads = get_training_loads(str(chat_id))
    acute_load_7d = loads.get("acute_load_7d", 0)
    chronic_load_28d = loads.get("chronic_load_28d", 0)
    acwr_data = calculate_acwr(acute_load_7d, chronic_load_28d)
    
    recent_log = get_recent_runs_log(str(chat_id), limit=5)
    long_term_memory = get_rag_context(query=f"Phân tích bài chạy {activity_name}", n_results=2)

    # 3. BUILD PROMPT CONTEXT
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

    # [NEW] SMART RETRY & GCS EXTRACTION
    max_retries = 3
    analysis_text = None
    
    for attempt in range(max_retries):
        try:
            response = chat_session.send_message(prompt) 
            analysis_text = response.text
            
            # REGEX bắt GCS mới: hỗ trợ 🎯 và format GCS (...): [X]%
            gcs_pattern = r"(?:🎯|GOAL CONFIDENCE SCORE|GCS).*?[:\s](\d{1,3})%"
            gcs_match = re.search(gcs_pattern, analysis_text, re.IGNORECASE | re.UNICODE)
            
            if gcs_match:
                gcs_score = int(gcs_match.group(1))
                gcs_score = max(0, min(100, gcs_score))
                update_run_gcs_score(activity_id, gcs_score)
                logger.info(f"[GCS] Captured: {gcs_score}% for Activity {activity_id}")
            break
        except Exception as api_err:
            if "429" in str(api_err):
                logger.warning(f"⚠️ [QUOTA] Limit reached. Sleeping 60s...")
                time.sleep(60)
            else:
                logger.error(f"API Error: {api_err}")
                break

    if not analysis_text: return None

    try:
        if chat_id:
            # Lưu tin nhắn và nạp vào ChromaDB với ID ép kiểu String
            save_message(str(chat_id), "model", f"[ANALYSIS] {activity_name}: {analysis_text}")
            
            memory_content = f"Sự kiện: VĐV chạy bài '{activity_name}' vào ngày {now.strftime('%Y-%m-%d')}.\nPhân tích:\n{analysis_text}"
            
            # QUAN TRỌNG: Ép kiểu str(activity_id) để tránh lỗi ChromaDB ID
            rag_db.memorize(
                doc_id=str(activity_id), 
                content=memory_content, 
                domain="coach", 
                extra_meta={"user_id": str(chat_id), "type": "run_analysis"}
            )
            logger.info(f"[RAG] Saved memory for activity: {activity_id}")
        return analysis_text
    except Exception as e:
        logger.error(f"Post-Analysis Save Error: {e}")
        return None

# handle_telegram_chat giữ nguyên phần logic cũ của bạn
def handle_telegram_chat(chat_id: str, text: str, config: dict):
    # ... logic handle_telegram_chat cũ ...
    pass