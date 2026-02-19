from fastapi import APIRouter, Request, BackgroundTasks
import os
import logging

from app.core.config import load_config
from app.core.notification import send_telegram_msg, send_html_email
from app.agents.coach.agent import analyze_run_with_gemini, handle_telegram_chat
from app.agents.coach.strava_client import StravaClient
from app.agents.coach.harvest import harvest_data

from app.core.state import state

router = APIRouter()
logger = logging.getLogger("AI_COACH")

# --- STRAVA WORKFLOW ---
def run_strava_workflow(activity_id: str):
    # Kiểm tra trạng thái chung trước khi chạy
    if not state.service_active: 
        logger.info(f"[WEBHOOK] Service is PAUSED. Ignoring Activity {activity_id}.")
        return
        
    config = load_config()
    client = StravaClient()
    
    logger.info(f"[*] Fetching data for Activity {activity_id}...")
    try:
        act_name, csv_data, meta_data = client.get_activity_data(activity_id)
    except ValueError:
        return
    
    if not csv_data: return

    logger.info("[*] Sending Data to Gemini...")
    analysis_text = analyze_run_with_gemini(activity_id, act_name, csv_data, meta_data, config)
    
    if analysis_text:
        # 1. Cập nhật lên Strava
        client.update_activity_description(activity_id, analysis_text)
        
        # 2. Gửi Email Báo Cáo
        email_body = f"""
        <h2>🏃‍♂️ Run Analysis: {act_name}</h2>
        <p><a href="https://www.strava.com/activities/{activity_id}">View on Strava</a></p>
        <hr>
        <pre style="white-space: pre-wrap; font-family: sans-serif;">{analysis_text}</pre>
        """
        send_html_email(f"Coach Dyno Report: {act_name}", email_body, config)

        # 3. [NEW] Gửi thông báo thẳng qua Telegram
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if chat_id:
            # Gắn link Strava vào tin nhắn để tiện bấm mở app trên điện thoại
            telegram_msg = (
                f"🏃‍♂️ **Phân tích bài chạy mới:** {act_name}\n\n"
                f"{analysis_text}\n\n"
                f"🔗 [Xem trên Strava](https://www.strava.com/activities/{activity_id})"
            )
            send_telegram_msg(chat_id, telegram_msg)
            logger.info(f"[*] Sent Telegram notification for Activity {activity_id}")
        
@router.post("/webhook")
async def strava_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    if data.get("object_type") == "activity" and data.get("aspect_type") == "create":
        activity_id = data.get("object_id")
        background_tasks.add_task(run_strava_workflow, activity_id)
    return {"status": "ok"}

@router.get("/webhook")
def verify_strava(request: Request):
    if request.query_params.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return {"hub.challenge": request.query_params.get("hub.challenge")}
    return {"error": "Invalid token"}

# --- TELEGRAM WORKFLOW ---
@router.post("/telegram-webhook")
async def telegram_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        
        # Bắt lệnh sync thủ công
        if text.strip() == "/sync":
            background_tasks.add_task(harvest_data)
            send_telegram_msg(chat_id, "⏳ Đang đồng bộ dữ liệu Strava...")
            return {"status": "ok"}

        config = load_config()
        # Chuyển tin nhắn cho Agent xử lý
        background_tasks.add_task(handle_telegram_chat, chat_id, text, config)
    return {"status": "ok"}