import os
import json
import logging
import google.generativeai as genai
from tools.notify_tools import send_telegram_msg
from tools.memory_db import save_message, load_history_for_gemini, clear_history

# Configure logging
logger = logging.getLogger(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def analyze_run_with_gemini(activity_id: str, activity_name: str, csv_data: str, config: dict):
    logger.info(f"[COACH AGENT] Analyzing run: {activity_name} (ID: {activity_id})")

    # 1. Setup Context & Dynamic Profile
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")
    
    dynamic_stats = ""
    stats_path = "data/athlete_stats.json"
    if os.path.exists(stats_path):
        try:
            with open(stats_path, "r") as f:
                s = json.load(f)
                dynamic_stats = (
                    f"\n[ATHLETE CURRENT TOTALS]:\n"
                    f"- Recent 4 weeks: {s.get('recent_run_totals', 0):.1f} km\n"
                    f"- Year to date: {s.get('ytd_run_totals', 0):.1f} km\n"
                )
        except Exception as e:
            logger.error(f"Error reading stats: {e}")

    full_instruction = f"{system_instruction}\n\n[USER PROFILE DATA]\n{user_profile}{dynamic_stats}"
    
    analysis_requirements = config.get("analysis_requirements", "Analyze HR and Power.")
    output_format = config.get("output_format", "Output in Vietnamese.")
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")

    # 2. Khởi tạo Model & Khôi phục trí nhớ
    try:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        history = load_history_for_gemini(chat_id, limit=10) if chat_id else []

        model = genai.GenerativeModel(
            model_name=current_model_name,
            system_instruction=full_instruction
        )
        
        chat_session = model.start_chat(history=history)
        
    except Exception as e:
        logger.error(f"Error initializing Agent Brain: {e}")
        return None

    # 3. Tạo Prompt phân tích
    prompt = f"""
    [TASK CONTEXT]
    Activity: {activity_name}
    
    [ANALYSIS REQUIREMENTS]
    {analysis_requirements}
    
    [OUTPUT FORMAT]
    {output_format}
    
    [RAW CSV DATA]
    {csv_data}
    """
    
    if config.get("debug_mode"):
        log_prompt = prompt.replace(csv_data, f"\n[...CSV HIDDEN {len(csv_data)} bytes...]\n")
        logger.info(f"[PROMPT PREVIEW WITH MEMORY]\n{log_prompt}")

    try:
        response = chat_session.send_message(prompt) 
        analysis_text = response.text

        if chat_id and analysis_text:
            save_message(str(chat_id), "model", f"[STRAVA ANALYSIS] {activity_name}: {analysis_text}")
            logger.info(f"[MEMORY] Analysis integrated for ID: {chat_id}")

        return analysis_text
        
    except Exception as e:
        logger.error(f"[COACH AGENT] Analysis Error: {e}")
        return None

def handle_telegram_chat(chat_id: str, text: str, config: dict):
    debug_mode = config.get("debug_mode", False)
    
    if text.strip().lower() in ["/clear", "/reset", "xóa nhớ"]:
        clear_history(chat_id)
        send_telegram_msg(chat_id, "🧹 Đã xóa bộ nhớ vĩnh cửu. Chúng ta bắt đầu lại nhé!")
        return

    current_model_name = config.get("model_name", "models/gemini-2.0-flash")
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")

    dynamic_stats = ""
    stats_path = "data/athlete_stats.json"
    if os.path.exists(stats_path):
        try:
            with open(stats_path, "r") as f:
                s = json.load(f)
                dynamic_stats = (
                    f"\n[ATHLETE CURRENT STATS]:\n"
                    f"- 4 tuần gần đây: {s.get('recent_run_totals', 0):.1f} km\n"
                    f"- Tổng năm nay: {s.get('ytd_run_totals', 0):.1f} km\n"
                )
        except Exception as e:
            logger.error(f"Error reading stats: {e}")

    full_persona = f"""
    {system_instruction}
    
    [USER PROFILE & CONTEXT]
    {user_profile}
    {dynamic_stats}
    
    [INSTRUCTION]
    - You are chatting directly with the user via Telegram.
    - Keep responses concise, helpful, and friendly.
    """

    try:
        current_history = load_history_for_gemini(chat_id, limit=20)

        model = genai.GenerativeModel(
            model_name=current_model_name,
            system_instruction=full_persona
        )
        
        chat_session = model.start_chat(history=current_history)
        response = chat_session.send_message(text)
        reply_text = response.text

        save_message(chat_id, "user", text)
        save_message(chat_id, "model", reply_text)

        if debug_mode:
            logger.info(f"[TELEGRAM] Chatting with DB history ({len(current_history)} turns).")

        send_telegram_msg(chat_id, reply_text)
        
    except Exception as e:
        logger.error(f"[TELEGRAM] Chat Error: {e}")
        if "400" in str(e) or "token" in str(e).lower():
            send_telegram_msg(chat_id, "⚠️ Bộ nhớ hội thoại quá dài. Hãy gõ /clear để dọn dẹp.")
        else:
            send_telegram_msg(chat_id, "⚠️ Coach Dyno đang bị 'chuột rút'. Thử /clear xem sao!")