import os
import sys
import logging
import json
import requests
import pandas as pd
import google.generativeai as genai
from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv

# --- CẤU HÌNH LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
app = FastAPI()

# Setup Gemini AI
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    # Dùng alias này để đảm bảo Free Tier luôn chạy ổn định
    model = genai.GenerativeModel('gemini-flash-latest')
    logger.info("Gemini AI Configured successfully.")
except Exception as e:
    logger.error(f"Error configuring Gemini: {e}", exc_info=True)

# --- HÀM ĐỌC CẤU HÌNH (MỚI) ---
def load_config():
    """Đọc file config.json để lấy prompt mới nhất"""
    try:
        config_path = "config.json"
        # Nếu chạy trong Docker mà không map volume đúng, cần đường dẫn tuyệt đối (tùy chọn)
        if not os.path.exists(config_path):
            logger.warning("Config file not found! Using default empty strings.")
            return {}
        
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config.json: {e}")
        return {}

def get_access_token():
    """Lấy Access Token từ Refresh Token"""
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
        logger.error(f"Error refreshing Strava token: {e}", exc_info=True)
        return None

def process_activity(activity_id):
    """Xử lý background task"""
    logger.info(f"[*] Processing Activity ID: {activity_id}")
    
    try:
        # 1. Load Cấu hình động (Dynamic Configuration)
        config = load_config()
        if not config:
            logger.error("Configuration is empty. Aborting to avoid bad prompt.")
            return

        # 2. Lấy Access Token
        access_token = get_access_token()
        if not access_token:
            logger.error("Failed to get Access Token. Stopping.")
            return

        headers = {'Authorization': f'Bearer {access_token}'}

        # 3. Lấy thông tin bài tập
        act_url = f"https://www.strava.com/api/v3/activities/{activity_id}"
        act_res = requests.get(act_url, headers=headers)
        if act_res.status_code != 200:
            logger.error(f"Failed to fetch activity. Status: {act_res.status_code}")
            return
            
        act_data = act_res.json()
        
        # Chỉ xử lý bài chạy
        allowed_types = ['Run', 'VirtualRun', 'TrailRun', 'Treadmill']
        if act_data.get('type') not in allowed_types:
            logger.warning(f"[-] Activity type is '{act_data.get('type')}'. Skipping.")
            return

        # 4. Lấy dữ liệu chi tiết (Streams)
        streams_url = f"{act_url}/streams?keys=time,heartrate,velocity_smooth,cadence,grade_smooth&key_by_type=true"
        streams_res = requests.get(streams_url, headers=headers).json()
        
        if 'message' in streams_res and streams_res['message'] == 'Record Not Found':
             logger.warning("Streams not found.")
             return

        # 5. Xử lý dữ liệu thành CSV
        data = {
            'Time_sec': streams_res.get('time', {}).get('data', []),
            'HR_bpm': streams_res.get('heartrate', {}).get('data', []),
            'Velocity_m_s': streams_res.get('velocity_smooth', {}).get('data', []),
            'Cadence_spm': streams_res.get('cadence', {}).get('data', []),
            'Grade_pct': streams_res.get('grade_smooth', {}).get('data', [])
        }
        
        df = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in data.items()]))
        
        if df.empty:
            logger.warning("Dataframe is empty.")
            return

        df.dropna(subset=['HR_bpm', 'Velocity_m_s'], inplace=True)
        csv_data = df.to_csv(index=False)
        logger.info(f"[+] Data fetched. Stream length: {len(df)} rows.")

        # 6. Tạo Prompt từ file Config
        prompt = f"""
        [System Instruction]
        {config.get('system_instruction', 'You are a running coach.')}
        
        [User Profile]
        {config.get('user_profile', '')}
        
        [Task]
        {config.get('task_description', 'Analyze this run.')}
        
        [Analysis Requirements]
        {config.get('analysis_requirements', '')}
        
        [Format]
        {config.get('output_format', '')}
        
        [Raw Data CSV]
        {csv_data}
        """
        
        logger.info("[*] Sending data to Gemini...")
        response = model.generate_content(prompt)
        
        if not response.text:
            logger.error("Gemini returned empty response.")
            return

        analysis_text = response.text + "\n\n---\n*Analysis generated by AI Coach (Gemini Flash)*"
        
        # 7. Cập nhật Strava
        update_data = {'description': analysis_text}
        update_res = requests.put(act_url, headers=headers, json=update_data)
        
        if update_res.status_code == 200:
            logger.info(f"[SUCCESS] Strava Activity {activity_id} updated successfully.")
        else:
            logger.error(f"[!] Failed to update Strava: {update_res.status_code}")

    except Exception as e:
        logger.critical(f"CRITICAL ERROR in process_activity: {e}", exc_info=True)

@app.get("/webhook")
def verify_webhook(request: Request):
    challenge = request.query_params.get("hub.challenge")
    verify_token = request.query_params.get("hub.verify_token")
    if verify_token == os.getenv("VERIFY_TOKEN"):
        return {"hub.challenge": challenge}
    return {"error": "Invalid verification token"}

@app.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        if data.get("object_type") == "activity" and data.get("aspect_type") == "create":
            background_tasks.add_task(process_activity, data.get("object_id"))
            logger.info(f"Queueing processing for Activity ID: {data.get('object_id')}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error"}