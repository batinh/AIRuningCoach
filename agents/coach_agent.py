import os
import logging
import google.generativeai as genai
from tools.notify_tools import send_telegram_msg

# --- GLOBAL MEMORY (Bộ nhớ ngắn hạn - RAM) ---
# Cấu trúc: { "chat_id": [history_object, ...] }
CHAT_HISTORY = {}
MAX_HISTORY_LEN = 20  # Chỉ nhớ 20 câu gần nhất để tiết kiệm Token

# Configure logging
logger = logging.getLogger(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# --- 1. WORKFLOW PHÂN TÍCH BÀI CHẠY (Giữ nguyên logic cũ) ---
def analyze_run_with_gemini(activity_id: str, activity_name: str, csv_data: str, config: dict):
    logger.info(f"[COACH AGENT] Analyzing run: {activity_name} (ID: {activity_id})")

    # 1. Setup Context
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")
    
    # Ghép Profile vào System Instruction để Bot hiểu sâu hơn
    full_instruction = f"{system_instruction}\n\n[USER PROFILE DATA]\n{user_profile}"
    
    analysis_requirements = config.get("analysis_requirements", "Analyze HR and Power.")
    output_format = config.get("output_format", "Output in Vietnamese.")
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")

    # 2. Khởi tạo Model
    try:
        model = genai.GenerativeModel(
            model_name=current_model_name,
            system_instruction=full_instruction
        )
    except Exception as e:
        logger.error(f"Error initializing model {current_model_name}: {e}")
        return None

    # 3. Tạo Prompt
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
    
    # Debug
    if config.get("debug_mode"):
        logger.info(f"[SYSTEM] Analyzing with Model: {current_model_name}")
        # Log prompt ẩn data
        log_prompt = prompt.replace(csv_data, f"\n[...CSV HIDDEN {len(csv_data)} bytes...]\n")
        logger.info(f"[PROMPT PREVIEW]\n{log_prompt}")

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"[COACH AGENT] Gemini Error: {e}")
        return None

# --- 2. WORKFLOW CHAT TELEGRAM (NÂNG CẤP CÓ TRÍ NHỚ) ---
def handle_telegram_chat(chat_id: str, text: str, config: dict):
    """
    Xử lý chat với bộ nhớ đệm (Contextual Memory).
    """
    debug_mode = config.get("debug_mode", False)
    
    # A. Xử lý lệnh đặc biệt
    if text.strip().lower() in ["/clear", "/reset", "xóa nhớ"]:
        if chat_id in CHAT_HISTORY:
            del CHAT_HISTORY[chat_id]
        send_telegram_msg(chat_id, "🧹 Đã xóa bộ nhớ tạm. Chúng ta bắt đầu lại nhé!")
        return

    # B. Cấu hình "Bộ não"
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")

    # C. Ghép "Nhân cách" + "Thông tin User" vào System Prompt
    # (Đây là bí quyết để start_chat vẫn nhớ bạn là ai)
    full_persona = f"""
    {system_instruction}
    
    [USER PROFILE & CONTEXT]
    {user_profile}
    
    [INSTRUCTION]
    - You are chatting directly with the user via Telegram.
    - Keep responses concise, helpful, and friendly.
    - Remember previous context in this conversation.
    """

    try:
        model = genai.GenerativeModel(
            model_name=current_model_name,
            system_instruction=full_persona
        )
    except Exception as e:
        logger.error(f"[TELEGRAM] Model Error: {e}")
        send_telegram_msg(chat_id, f"⚠️ Lỗi model {current_model_name}. Hãy đổi model khác trên Web Admin.")
        return

    # D. Khôi phục lịch sử chat từ RAM
    # Nếu chưa có thì tạo list rỗng
    current_history = CHAT_HISTORY.get(chat_id, [])

    if debug_mode:
        logger.info(f"[TELEGRAM] Chatting with history ({len(current_history)} turns). Model: {current_model_name}")

    try:
        # E. BẮT ĐẦU CHAT VỚI LỊCH SỬ CŨ
        chat_session = model.start_chat(history=current_history)
        
        # Gửi tin nhắn mới
        response = chat_session.send_message(text)
        reply_text = response.text

        # F. Cập nhật lại lịch sử vào RAM
        # Chỉ giữ lại MAX_HISTORY_LEN tin mới nhất để tiết kiệm
        updated_history = chat_session.history
        if len(updated_history) > MAX_HISTORY_LEN:
            updated_history = updated_history[-MAX_HISTORY_LEN:]
        
        CHAT_HISTORY[chat_id] = updated_history

        # Gửi kết quả
        send_telegram_msg(chat_id, reply_text)
        
    except Exception as e:
        logger.error(f"[TELEGRAM] Chat Error: {e}")
        # Nếu lỗi (do token quá dài hoặc model crash), thử xóa nhớ và chat lại 1 lần
        if "400" in str(e) or "token" in str(e).lower():
            if chat_id in CHAT_HISTORY:
                del CHAT_HISTORY[chat_id]
                send_telegram_msg(chat_id, "⚠️ Bộ nhớ đầy, tôi đã tự động reset để tiếp tục cuộc trò chuyện.")
                # Thử gọi lại đệ quy 1 lần (cẩn thận loop)
                # handle_telegram_chat(chat_id, text, config) 
        else:
            send_telegram_msg(chat_id, "⚠️ Coach Dyno đang bị 'chuột rút' (Lỗi API). Thử /clear xem sao!")