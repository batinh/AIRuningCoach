import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def send_telegram_msg(chat_id, text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("[TELEGRAM] No token found in environment variables.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown" # Để bot in đậm/nghiêng đẹp hơn
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"[TELEGRAM] Failed to send message: {response.text}")
    except Exception as e:
        logger.error(f"[TELEGRAM] Connection error: {e}")