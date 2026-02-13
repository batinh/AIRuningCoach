import os
import logging
from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv

from agents.coach_agent import process_strava_run, handle_telegram_chat

# Initialize environment and logging
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# ==========================================
# 1. STRAVA WEBHOOK ROUTING
# ==========================================
@app.get("/webhook")
def verify_strava(request: Request):
    """Handle Strava webhook verification."""
    if request.query_params.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return {"hub.challenge": request.query_params.get("hub.challenge")}
    return {"error": "Invalid token"}

@app.post("/webhook")
async def strava_event(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming run data from Strava."""
    data = await request.json()
    
    # Check if this is a new activity creation
    if data.get("object_type") == "activity" and data.get("aspect_type") == "create":
        activity_id = data.get("object_id")
        logger.info(f"[GATEWAY] Received new Strava Activity: {activity_id}. Routing to Coach Dyno.")
        
        # Dispatch to background task to prevent Strava webhook timeout
        background_tasks.add_task(process_strava_run, activity_id)
        
    return {"status": "ok"}

# ==========================================
# 2. TELEGRAM WEBHOOK ROUTING
# ==========================================
@app.post("/telegram-webhook")
async def telegram_event(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming messages from Telegram Bot."""
    data = await request.json()
    
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        
        logger.info(f"[GATEWAY] Received Telegram message from {chat_id}: {text}")
        
        # Simple router based on message commands
        if text.startswith("/news"):
            # Placeholder for future News Agent
            # background_tasks.add_task(process_news, chat_id, text)
            pass
        else:
            # Default routing to Coach Agent
            background_tasks.add_task(handle_telegram_chat, chat_id, text)
            
    return {"status": "ok"}