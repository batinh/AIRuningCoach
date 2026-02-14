import os
import logging
import google.generativeai as genai
from tools.notify_tools import send_telegram_msg
# Configure logging
logger = logging.getLogger(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def analyze_run_with_gemini(activity_id: str, activity_name: str, csv_data: str, config: dict):
    """
    Sends Raw Run Data (CSV) to Gemini for detailed analysis.
    """
    logger.info(f"[COACH AGENT] Analyzing run: {activity_name} (ID: {activity_id})")

    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")
    analysis_requirements = config.get("analysis_requirements", "Analyze HR and Power.")
    output_format = config.get("output_format", "Output in Vietnamese.")
    
    # --- DEBUG: CHECK MODE ---
    debug_mode = config.get("debug_mode", False)
    
    # 1. LẤY TÊN MODEL TỪ CONFIG (Live Affect)
    # Mặc định về 2.0 Flash nếu config chưa có
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")
    
    if config.get("debug_mode"):
        logger.info(f"[SYSTEM] Initializing AI Brain: {current_model_name}")
    
    # 2. KHỞI TẠO CLIENT
    try:
        model = genai.GenerativeModel(
            model_name=current_model_name,
            system_instruction=system_instruction
        )
        # ... tiếp tục logic generate ...
    except Exception as e:
        logger.error(f"Error initializing model {current_model_name}: {e}")
        return None

    # Construct Prompt
    prompt = f"""
    [TASK CONTEXT]
    Activity Name: {activity_name}
    User Profile: {user_profile}
    
    [ANALYSIS REQUIREMENTS]
    {analysis_requirements}
    
    [OUTPUT FORMAT INSTRUCTION]
    {output_format}
    
    [RAW DATA - CSV FORMAT]
    (Time, HR, Velocity, Cadence, Grade)
    {csv_data}
    """
    
# --- DEBUG: LOG PROMPT (CLEAN VERSION) ---
    if debug_mode:
        logger.info("="*30 + " [DEBUG] PROMPT TO GEMINI " + "="*30)
        
        # Tạo bản sao của prompt để log, thay thế data thật bằng placeholder
        # Cách này giúp anh vẫn nhìn thấy System Instruction & User Profile
        log_prompt = prompt.replace(csv_data, f"\n[...RAW CSV DATA HIDDEN ({len(csv_data)} bytes)...]\n")
        
        logger.info(log_prompt)
        logger.info("="*80)
    try:
        response = model.generate_content(prompt)
        analysis_text = response.text
        
        # --- DEBUG: LOG FULL RESPONSE ---
        if debug_mode:
            logger.info("="*30 + " [DEBUG] GEMINI RAW RESPONSE " + "="*30)
            logger.info(analysis_text)
            logger.info("="*80)
            
        logger.info("[COACH AGENT] Analysis generated successfully.")
        return analysis_text
    except Exception as e:
        logger.error(f"[COACH AGENT] Gemini Error: {e}")
        return None

def handle_telegram_chat(chat_id: str, text: str, config: dict):
    """
    Workflow triggered when the user sends a message via Telegram.
    """
    # 1. Check Debug Mode & Log
    debug_mode = config.get("debug_mode", False)
    if debug_mode:
        logger.info(f"[TELEGRAM] Processing message from {chat_id}: {text}")

    # 2. Lấy tên Model từ Config (Live Switch)
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")
    
    # 3. Lấy System Instruction
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")

    # 4. Khởi tạo Model (Local Scope)
    try:
        model = genai.GenerativeModel(
            model_name=current_model_name,
            system_instruction=system_instruction
        )
    except Exception as e:
        logger.error(f"[TELEGRAM] Error initializing model {current_model_name}: {e}")
        send_telegram_msg(chat_id, "⚠️ System Error: Invalid AI Model configuration.")
        return

    # 5. Tạo Prompt
    prompt = f"""
    [USER CONTEXT]
    {user_profile}

    [USER MESSAGE]
    {text}
    
    [INSTRUCTION]
    Reply directly to the user. Be concise, strict but helpful.
    """
    
    if debug_mode:
        logger.info("="*30 + " [TELEGRAM DEBUG PROMPT] " + "="*30)
        logger.info(prompt)

    try:
        # 6. Gọi Gemini
        response = model.generate_content(prompt)
        reply_text = response.text
        
        if debug_mode:
            logger.info(f"[TELEGRAM DEBUG RESPONSE]: {reply_text}")

        # 7. Gửi phản hồi về Telegram
        send_telegram_msg(chat_id, reply_text)
        
    except Exception as e:
        # --- ĐÂY LÀ ĐOẠN BỊ LỖI TRƯỚC ĐÓ, HÃY CHÉP KỸ ---
        logger.error(f"[TELEGRAM] Error during chat handling: {e}")
        send_telegram_msg(chat_id, "⚠️ Coach Dyno đang bị 'chuột rút' (Lỗi API). Thử lại sau nhé!")