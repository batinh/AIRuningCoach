import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import deque
from typing import Optional

from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv

# --- SỬA DÒNG IMPORT QUAN TRỌNG NÀY ---
# Import đúng hàm mới từ coach_agent và tool Strava
from agents.coach_agent import analyze_run_with_gemini, handle_telegram_chat
from tools.strava_client import StravaClient

# --- SETUP ---
load_dotenv()

# Logging for Admin Dashboard
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
    Gửi email báo cáo.
    - Server config: Lấy từ config.json
    - Credentials: Lấy từ biến môi trường (.env)
    """
    # 1. Lấy Config công khai từ JSON
    email_cfg = config.get("email_config", {})
    if not email_cfg.get("enabled"): 
        return

    # 2. Lấy Credentials bí mật từ ENV
    env_sender = os.getenv("EMAIL_SENDER")
    env_password = os.getenv("EMAIL_PASSWORD")
    env_receiver = os.getenv("EMAIL_RECEIVER")
    
    # Kiểm tra xem có đủ thông tin đăng nhập không
    if not all([env_sender, env_password, env_receiver]):
        logger.error("[EMAIL] Thiếu thông tin đăng nhập trong .env (EMAIL_SENDER/PASSWORD/RECEIVER)")
        return

    try:
        # 3. Lấy Server Info từ JSON (Nếu không có thì dùng mặc định Gmail)
        smtp_server = email_cfg.get('smtp_server', 'smtp.gmail.com')
        smtp_port = int(email_cfg.get('smtp_port', 587))

        # 4. Cấu hình Email Message
        msg = MIMEMultipart()
        # [QUAN TRỌNG] Dùng biến từ ENV, KHÔNG dùng email_cfg['sender_email'] nữa
        msg['From'] = env_sender       
        msg['To'] = env_receiver       
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))

        # 5. Kết nối và Gửi
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        # Đăng nhập bằng credentials từ ENV
        server.login(env_sender, env_password)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"[EMAIL] Sent report to {env_receiver}")
        
    except Exception as e:
        logger.error(f"[EMAIL] Failed: {e}")
# --- WORKFLOW: STRAVA PROCESS ---
def run_strava_workflow(activity_id: str):
    if not SERVICE_ACTIVE: return
    
    config = load_config()
    client = StravaClient()
    
    # 1. Fetch Data & Convert to CSV
    logger.info(f"[*] Fetching data for Activity {activity_id}...")
    act_name, csv_data = client.get_activity_data(activity_id)
    
    if not csv_data:
        logger.warning("[!] No valid data found (or not a run).")
        return

    # 2. Analyze with Gemini
    logger.info("[*] Sending CSV data to Gemini...")
    # Gọi đúng tên hàm mới ở đây
    analysis_text = analyze_run_with_gemini(activity_id, act_name, csv_data, config)
    
    if analysis_text:
        # 3. Update Strava Description
        client.update_activity_description(activity_id, analysis_text)
        
        # 4. Send Email Report
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
    
    # Email Config
    if "email_config" not in config: config["email_config"] = {}
    config["email_config"]["enabled"] = True if email_enabled == "on" else False
    config["email_config"]["smtp_server"] = "smtp.gmail.com"
    config["email_config"]["smtp_port"] = 587
    # --- 2. THÊM ĐOẠN NÀY ĐỂ LƯU DEBUG MODE ---
    config["debug_mode"] = True if debug_mode == "on" else False
    # ------------------------------------------
    # --- CẬP NHẬT MODEL ---
    config["model_name"] = model_name
    save_config(config)
    logger.info(f"Configuration saved. Active Model: {config['model_name']}")
    # Log ra để kiểm tra
    logger.info(f"Config Saved. Debug Mode is now: {config['debug_mode']}")
    
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
    if data.get("object_type") == "activity" and data.get("aspect_type") == "create":
        activity_id = data.get("object_id")
        logger.info(f"[WEBHOOK] New Activity {activity_id}. Starting workflow.")
        background_tasks.add_task(run_strava_workflow, activity_id)
    return {"status": "ok"}

@app.get("/webhook")
def verify_strava(request: Request):
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
        config = load_config()
        background_tasks.add_task(handle_telegram_chat, chat_id, text, config)
    return {"status": "ok"}