import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import deque
from typing import Optional
from datetime import datetime
import pytz

from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv

# --- SCHEDULER IMPORTS ---
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- MODULE IMPORTS ---
from agents.coach_agent import analyze_run_with_gemini, handle_telegram_chat
from tools.strava_client import StravaClient
from tools.memory_db import init_db
from tools.notify_tools import send_telegram_msg
# Ensure harvest_strava.py is in the root directory or properly packaged
from harvest_strava import harvest_data

# Initialize Database
init_db()

# --- SETUP ---
load_dotenv()

# Logging Configuration for Admin Dashboard
log_capture_string = deque(maxlen=50)
class ListHandler(logging.Handler):
    def emit(self, record):
        log_capture_string.append(self.format(record))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AI_COACH")
logger.addHandler(ListHandler())

app = FastAPI()
templates = Jinja2Templates(directory="templates")
CONFIG_PATH = "data/config.json"
SERVICE_ACTIVE = True

# Initialize Scheduler
scheduler = AsyncIOScheduler()
TZ_VN = pytz.timezone('Asia/Ho_Chi_Minh')

# --- SCHEDULED TASKS ---

async def task_morning_briefing():
    """
    Sends a morning briefing message to Telegram at 06:00 AM daily.
    Includes year-to-date stats and a greeting.
    """
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        # Fetch latest statistics
        stats = {}
        if os.path.exists("data/athlete_stats.json"):
            try:
                with open("data/athlete_stats.json", "r") as f:
                    stats = json.load(f)
            except Exception as e:
                logger.error(f"[SCHEDULER] Failed to read stats: {e}")
        
        ytd_km = stats.get('ytd_run_totals', 0)
        recent_km = stats.get('recent_run_totals', 0) # Last 4 weeks
        
        # Message content in Vietnamese (User Interface language)
        msg = (
            f"☀️ **CHÀO BUỔI SÁNG COACH DYNO!**\n"
            f"📅 Hôm nay là: {datetime.now(TZ_VN).strftime('%A, %d/%m')}\n"
            f"--------------------------------\n"
            f"📊 **Tổng kết nhanh:**\n"
            f"▪️ Tổng năm nay: `{ytd_km:.1f} km`\n"
            f"▪️ Volume 4 tuần: `{recent_km:.1f} km`\n\n"
            f"💡 *Gõ /sync để cập nhật dữ liệu mới nhất từ Strava nếu cậu vừa chạy xong!*"
        )
        send_telegram_msg(chat_id, msg)
        logger.info("[SCHEDULER] Sent Morning Briefing.")

async def task_auto_harvest():
    """
    Automatically harvests Strava data every 6 hours to keep stats updated.
    """
    logger.info("[SCHEDULER] Auto-harvesting Strava Data...")
    try:
        # Execute harvest function
        harvest_data() 
        logger.info("[SCHEDULER] Harvest complete.")
    except Exception as e:
        logger.error(f"[SCHEDULER] Harvest failed: {e}")

# --- LIFECYCLE EVENTS ---
@app.on_event("startup")
async def start_scheduler():
    """
    Start the scheduler when the FastAPI app starts.
    """
    # 1. Job: Morning Briefing at 06:00 AM VN Time
    scheduler.add_job(
        task_morning_briefing, 
        CronTrigger(hour=6, minute=0, timezone=TZ_VN),
        id="morning_briefing",
        replace_existing=True
    )
    
    # 2. Job: Auto Harvest every 6 hours (0, 6, 12, 18:15)
    scheduler.add_job(
        task_auto_harvest,
        CronTrigger(hour='0,6,12,18', minute=15, timezone=TZ_VN),
        id="auto_harvest",
        replace_existing=True
    )

    scheduler.start()
    logger.info("[SYSTEM] Scheduler started (Morning Briefing & Auto Harvest).")

@app.on_event("shutdown")
async def stop_scheduler():
    """
    Stop the scheduler when the app shuts down.
    """
    scheduler.shutdown()
    logger.info("[SYSTEM] Scheduler shut down.")

# --- HELPER FUNCTIONS ---
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_config(data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def send_html_email(subject, html_content, config):
    """
    Sends an HTML email report using SMTP configuration.
    """
    email_cfg = config.get("email_config", {})
    if not email_cfg.get("enabled"): return

    env_sender = os.getenv("EMAIL_SENDER")
    env_password = os.getenv("EMAIL_PASSWORD")
    env_receiver = os.getenv("EMAIL_RECEIVER")
    
    if not all([env_sender, env_password, env_receiver]):
        logger.error("[EMAIL] Missing EMAIL_SENDER/PASSWORD/RECEIVER in .env")
        return

    try:
        smtp_server = email_cfg.get('smtp_server', 'smtp.gmail.com')
        smtp_port = int(email_cfg.get('smtp_port', 587))

        msg = MIMEMultipart()
        msg['From'] = env_sender       
        msg['To'] = env_receiver       
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(env_sender, env_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"[EMAIL] Sent report to {env_receiver}")
    except Exception as e:
        logger.error(f"[EMAIL] Failed to send email: {e}")

# --- WORKFLOW: STRAVA PROCESS ---
def run_strava_workflow(activity_id: str):
    """
    Main workflow: Fetch Data -> Analyze with Gemini -> Update Strava -> Notify.
    """
    if not SERVICE_ACTIVE: return
    
    config = load_config()
    client = StravaClient()
    
    logger.info(f"[*] Fetching data for Activity {activity_id}...")
    try:
        # Expecting 3 return values now
        act_name, csv_data, meta_data = client.get_activity_data(activity_id)
    except ValueError:
        logger.error("[ERROR] StravaClient mismatch. Ensure get_activity_data returns 3 values.")
        return
    
    if not csv_data:
        logger.warning("[!] No valid data found (or not a run).")
        return

    logger.info("[*] Sending Data (CSV + Splits) to Gemini...")
    analysis_text = analyze_run_with_gemini(activity_id, act_name, csv_data, meta_data, config)
    
    if analysis_text:
        # Update Strava Description
        client.update_activity_description(activity_id, analysis_text)
        
        # Send Email Report
        email_body = f"""
        <h2>🏃‍♂️ Run Analysis: {act_name}</h2>
        <p><a href="https://www.strava.com/activities/{activity_id}">View on Strava</a></p>
        <hr>
        <pre style="white-space: pre-wrap; font-family: sans-serif;">{analysis_text}</pre>
        """
        send_html_email(f"Coach Dyno Report: {act_name}", email_body, config)

# --- ROUTES ---
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "config": load_config(),
        "logs": "\n".join(list(log_capture_string)),
        "service_active": SERVICE_ACTIVE
    })

@app.post("/admin/save")
async def save_settings(
    request: Request,
    system_instruction: str = Form(...),
    user_profile: str = Form(...),
    task_description: str = Form(...),
    analysis_requirements: str = Form(...),
    output_format: str = Form(...),
    email_enabled: Optional[str] = Form(None),
    debug_mode: Optional[str] = Form(None),
    model_name: str = Form("models/gemini-2.0-flash")
):
    config = load_config()
    config["system_instruction"] = system_instruction
    config["user_profile"] = user_profile
    config["task_description"] = task_description
    config["analysis_requirements"] = analysis_requirements
    config["output_format"] = output_format
    
    # Update Email Config
    if "email_config" not in config: config["email_config"] = {}
    config["email_config"]["enabled"] = True if email_enabled == "on" else False
    config["email_config"]["smtp_server"] = "smtp.gmail.com"
    config["email_config"]["smtp_port"] = 587
    
    # Update Debug Mode & Model
    config["debug_mode"] = True if debug_mode == "on" else False
    config["model_name"] = model_name
    
    save_config(config)
    logger.info(f"Configuration saved. Active Model: {config['model_name']}")
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/admin/test-email")
async def test_email_route():
    try:
        cfg = load_config()
        send_html_email("Test Email", "<h1>It Works!</h1>", cfg)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/webhook")
async def strava_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    # Check for new activity creation event
    if data.get("object_type") == "activity" and data.get("aspect_type") == "create":
        activity_id = data.get("object_id")
        logger.info(f"[WEBHOOK] New Activity {activity_id}. Starting workflow.")
        background_tasks.add_task(run_strava_workflow, activity_id)
    return {"status": "ok"}

@app.get("/webhook")
def verify_strava(request: Request):
    # Verify Strava Webhook subscription
    if request.query_params.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return {"hub.challenge": request.query_params.get("hub.challenge")}
    return {"error": "Invalid token"}

@app.post("/telegram-webhook")
async def telegram_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        logger.info(f"[GATEWAY] Received Telegram: {text}")
        
        # [COMMAND] Manual Sync
        if text.strip() == "/sync":
            send_telegram_msg(chat_id, "⏳ Syncing Strava data...")
            try:
                harvest_data()
                send_telegram_msg(chat_id, "✅ Sync complete! Stats updated.")
            except Exception as e:
                send_telegram_msg(chat_id, f"❌ Sync failed: {e}")
            return {"status": "ok"}

        # Normal Chat Handling
        config = load_config()
        background_tasks.add_task(handle_telegram_chat, chat_id, text, config)
    return {"status": "ok"}