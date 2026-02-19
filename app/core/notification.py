import os
import logging
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
        "parse_mode": "Markdown" 
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"[TELEGRAM] Failed to send message: {response.text}")
    except Exception as e:
        logger.error(f"[TELEGRAM] Connection error: {e}")

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