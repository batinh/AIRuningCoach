import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def send_telegram_msg(chat_id: str, message: str) -> bool:
    """Send an HTML-formatted message via Telegram Bot API."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not bot_token or not chat_id:
        logger.error("[Notify Tool] Telegram Bot Token or Chat ID is missing.")
        return False
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"[Notify Tool] Telegram API Error: {e}")
        return False