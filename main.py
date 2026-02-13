import os
import sys
import logging
import json
import requests
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
from fastapi import FastAPI, Request, BackgroundTasks, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# --- 1. SETUP LOGGING (Ghi ra file để Web đọc được) ---
log_file = "app.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- 2. CONFIG & VARS ---
load_dotenv()
app = FastAPI()
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

# Global State
SERVICE_ACTIVE = True 

def load_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {}

def save_config(new_config):
    try:
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=4, ensure_ascii=False)
        logger.info("Configuration saved successfully via Admin Dashboard.")
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False

# --- 3. AUTHENTICATION ---
def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    config = load_config()
    correct_user = config.get("admin_auth", {}).get("username", "admin")
    correct_pass = config.get("admin_auth", {}).get("password", "123")
    
    if credentials.username != correct_user or credentials.password != correct_pass:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- 4. EMAIL FUNCTION ---
def send_email_notification(subject, body_html):
    config = load_config()
    email_conf = config.get("email_config", {})
    
    if not email_conf.get("enabled", False):
        logger.info("Email notification is disabled.")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = email_conf['sender_email']
        msg['To'] = email_conf['receiver_email']
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html')) # Gửi dạng HTML để đẹp

        server = smtplib.SMTP(email_conf['smtp_server'], email_conf['smtp_port'])
        server.starttls()
        server.login(email_conf['sender_email'], email_conf['sender_password'])
        text = msg.as_string()
        server.sendmail(email_conf['sender_email'], email_conf['receiver_email'], text)
        server.quit()
        logger.info(f"📧 Email sent to {email_conf['receiver_email']}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

# --- 5. CORE LOGIC (AI + STRAVA) ---
# (Setup Gemini)
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-flash-latest')
except Exception as e:
    logger.error(f"Error configuring Gemini: {e}")

def get_access_token():
    url = "https://www.strava.com/oauth/token"
    payload = {
        'client_id': os.getenv("STRAVA_CLIENT_ID"),
        'client_secret': os.getenv("STRAVA_CLIENT_SECRET"),
        'refresh_token': os.getenv("STRAVA_REFRESH_TOKEN"),
        'grant_type': 'refresh_token'
    }
    try:
        res = requests.post(url, data=payload)
        res.raise_for_status()
        return res.json().get('access_token')
    except Exception as e:
        logger.error(f"Error refreshing Strava token: {e}")
        return None

def process_activity(activity_id):
    if not SERVICE_ACTIVE:
        logger.warning(f"Service is PAUSED. Skipping activity {activity_id}.")
        return

    logger.info(f"[*] Processing Activity ID: {activity_id}")
    config = load_config()
    
    try:
        access_token = get_access_token()
        if not access_token: return

        headers = {'Authorization': f'Bearer {access_token}'}
        
        # 1. Fetch Activity
        act_url = f"https://www.strava.com/api/v3/activities/{activity_id}"
        act_res = requests.get(act_url, headers=headers)
        if act_res.status_code != 200: return
        act_data = act_res.json()
        
        if act_data.get('type') not in ['Run', 'VirtualRun', 'TrailRun', 'Treadmill']:
            logger.info("Not a run. Skipping.")
            return

        # 2. Fetch Streams
        streams_url = f"{act_url}/streams?keys=time,heartrate,velocity_smooth,cadence,grade_smooth&key_by_type=true"
        streams_res = requests.get(streams_url, headers=headers).json()
        
        # 3. Prepare Data
        data = {
            'Time_sec': streams_res.get('time', {}).get('data', []),
            'HR_bpm': streams_res.get('heartrate', {}).get('data', []),
            'Velocity_m_s': streams_res.get('velocity_smooth', {}).get('data', []),
            'Cadence_spm': streams_res.get('cadence', {}).get('data', []),
            'Grade_pct': streams_res.get('grade_smooth', {}).get('data', [])
        }
        df = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in data.items()]))
        df.dropna(subset=['HR_bpm', 'Velocity_m_s'], inplace=True)
        csv_data = df.to_csv(index=False)

        # 4. Call Gemini
        prompt = f"""
        [System Instruction] {config.get('system_instruction')}
        [User Profile] {config.get('user_profile')}
        [Task] {config.get('task_description')}
        [Requirements] {config.get('analysis_requirements')}
        [Format] {config.get('output_format')}
        [Raw Data CSV] {csv_data}
        """
        
        logger.info("[*] Sending data to Gemini...")
        response = model.generate_content(prompt)
        analysis_text = response.text
        logger.info("[+] Analysis received.")

        # 5. Update Strava
        update_res = requests.put(act_url, headers=headers, json={'description': analysis_text})
        if update_res.status_code == 200:
            logger.info(f"[SUCCESS] Strava Updated.")
            
            # 6. SEND EMAIL
            email_body = f"""
            <h3>🏃‍♂️ New Run Analyzed!</h3>
            <p><b>Activity:</b> {act_data.get('name')}</p>
            <p><b>Link:</b> <a href="https://www.strava.com/activities/{activity_id}">View on Strava</a></p>
            <hr>
            <pre style="white-space: pre-wrap;">{analysis_text}</pre>
            """
            send_email_notification(f"AI Coach Report: {act_data.get('name')}", email_body)
        else:
            logger.error(f"Failed to update Strava: {update_res.text}")

    except Exception as e:
        logger.critical(f"CRITICAL ERROR: {e}", exc_info=True)

# --- 6. WEB ROUTES (WEBHOOK + ADMIN) ---

@app.get("/webhook")
def verify_webhook(request: Request):
    if request.query_params.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return {"hub.challenge": request.query_params.get("hub.challenge")}
    return {"error": "Invalid token"}

@app.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        if data.get("object_type") == "activity" and data.get("aspect_type") == "create":
            background_tasks.add_task(process_activity, data.get("object_id"))
            logger.info(f"Webhook received for Activity {data.get('object_id')}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error"}

# --- ADMIN ROUTES ---
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, username: str = Depends(get_current_username)):
    config = load_config()
    # Read last 50 lines of logs
    logs = ""
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            logs = "".join(f.readlines()[-50:])
            
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "config": config,
        "logs": logs,
        "service_active": SERVICE_ACTIVE
    })

@app.post("/admin/save")
def admin_save(
    request: Request,
    system_instruction: str = Form(...),
    user_profile: str = Form(...),
    task_description: str = Form(...),
    analysis_requirements: str = Form(...),
    output_format: str = Form(...),
    email_sender: str = Form(...),
    email_password: str = Form(...),
    email_receiver: str = Form(...),
    email_enabled: str = Form(None), # Checkbox trả về None nếu không tick
    username: str = Depends(get_current_username)
):
    config = load_config()
    
    # Update logic fields
    config['system_instruction'] = system_instruction
    config['user_profile'] = user_profile
    config['task_description'] = task_description
    config['analysis_requirements'] = analysis_requirements
    config['output_format'] = output_format
    
    # Update Email fields
    config['email_config']['sender_email'] = email_sender
    config['email_config']['sender_password'] = email_password
    config['email_config']['receiver_email'] = email_receiver
    config['email_config']['enabled'] = True if email_enabled else False
    
    save_config(config)
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/toggle")
def admin_toggle(username: str = Depends(get_current_username)):
    global SERVICE_ACTIVE
    SERVICE_ACTIVE = not SERVICE_ACTIVE
    logger.info(f"Service status changed to: {'RUNNING' if SERVICE_ACTIVE else 'PAUSED'}")
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/admin/test-email")
def test_email(username: str = Depends(get_current_username)):
    send_email_notification("Test Email from AI Coach", "<h1>It Works!</h1><p>Hệ thống gửi mail hoạt động tốt.</p>")
    return RedirectResponse(url="/admin", status_code=303)