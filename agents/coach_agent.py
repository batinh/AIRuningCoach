import json
import os
import logging
import google.generativeai as genai
from tools.notify_tools import send_telegram_msg
from tools.memory_db import save_message, load_history_for_gemini, clear_history
# --- GLOBAL MEMORY (Bộ nhớ ngắn hạn - RAM) ---
# Cấu trúc: { "chat_id": [historxy_object, ...] }
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
    
    if config.get("debug_mode"):
        logger.info(f"[SYSTEM] Analyzing with Model: {current_model_name}")
        # Log prompt ẩn data
        log_prompt = prompt.replace(csv_data, f"\n[...CSV HIDDEN {len(csv_data)} bytes...]\n")
        logger.info(f"[PROMPT PREVIEW]\n{log_prompt}")
    try:
        # 4. Gọi Gemini để phân tích
        response = model.generate_content(prompt)
        analysis_text = response.text

        # 🚀 BƯỚC HỢP NHẤT: Lưu phân tích vào trí nhớ hội thoại
        # Lấy Chat ID từ biến môi trường hoặc config để định danh ngăn kéo bộ nhớ của TinhN
        import os
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if chat_id and analysis_text:
            # Lưu vào DB với tiền tố [STRAVA] để AI sau này dễ nhận diện
            save_message(str(chat_id), "model", f"[STRAVA ANALYSIS] {activity_name}: {analysis_text}")
            logger.info(f"[MEMORY] Analysis merged into Chat History for ID: {chat_id}")

        return analysis_text
        
    except Exception as e:
        logger.error(f"[COACH AGENT] Gemini Error: {e}")
        return None
# --- 2. WORKFLOW CHAT TELEGRAM (NÂNG CẤP CÓ TRÍ NHỚ) ---

def handle_telegram_chat(chat_id: str, text: str, config: dict):
    """
    Xử lý chat với bộ nhớ vĩnh cửu (SQLite Persistent Memory).
    """
    debug_mode = config.get("debug_mode", False)
    
    # A. Xử lý lệnh đặc biệt
    if text.strip().lower() in ["/clear", "/reset", "xóa nhớ"]:
        clear_history(chat_id) # Xóa trong DB
        send_telegram_msg(chat_id, "🧹 Đã xóa bộ nhớ vĩnh cửu. Chúng ta bắt đầu lại nhé!")
        return

    # B. Cấu hình "Bộ não" (Giữ nguyên logic cũ)
    current_model_name = config.get("model_name", "models/gemini-2.0-flash")
    system_instruction = config.get("system_instruction", "You are Coach Dyno.")
    user_profile = config.get("user_profile", "")
# --- ĐỌC STATS TỪ FILE THU HOẠCH ---
    dynamic_stats = ""
    stats_path = "data/athlete_stats.json"
    if os.path.exists(stats_path):
        try:
            with open(stats_path, "r") as f:
                s = json.load(f)
                dynamic_stats = (
                    f"\n[ATHLETE CURRENT STATS]:\n"
                    f"- 4 tuần gần đây: {s['recent_run_totals']:.1f} km\n"
                    f"- Tổng năm nay: {s['ytd_run_totals']:.1f} km\n"
                )
        except Exception as e:
            logger.error(f"Error reading stats: {e}")
    full_persona = f"""
    {system_instruction}
    
    [USER PROFILE & CONTEXT]
    {user_profile}
    
    [INSTRUCTION]
    - You are chatting directly with the user via Telegram.
    - Keep responses concise, helpful, and friendly.
    """

    try:
        # C. Khôi phục lịch sử chat từ SQLITE
        current_history = load_history_for_gemini(chat_id, limit=20)

        model = genai.GenerativeModel(
            model_name=current_model_name,
            system_instruction=full_persona
        )
        
        # D. BẮT ĐẦU CHAT VỚI LỊCH SỬ CŨ
        # Lưu ý: Gemini tự động lưu tin nhắn mới vào chat_session.history
        chat_session = model.start_chat(history=current_history)
        
        # Gửi tin nhắn mới
        response = chat_session.send_message(text)
        reply_text = response.text

        # E. LƯU CẢ TIN NHẮN MỚI VÀ PHẢN HỒI VÀO DB
        save_message(chat_id, "user", text)
        save_message(chat_id, "model", reply_text)

        if debug_mode:
            logger.info(f"[TELEGRAM] Chatting with DB history ({len(current_history)} turns).")

        # F. Gửi kết quả
        send_telegram_msg(chat_id, reply_text)
        
    except Exception as e:
        logger.error(f"[TELEGRAM] Chat Error: {e}")
        if "400" in str(e) or "token" in str(e).lower():
            send_telegram_msg(chat_id, "⚠️ Bộ nhớ hội thoại quá dài. Hãy gõ /clear để dọn dẹp.")
        else:
            send_telegram_msg(chat_id, "⚠️ Coach Dyno đang bị 'chuột rút'. Thử /clear xem sao!")