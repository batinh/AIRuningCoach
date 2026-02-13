import os
import json
import logging
import google.generativeai as genai

from tools.notify_tools import send_telegram_msg
from tools.strava_tools import calculate_trimp

logger = logging.getLogger(__name__)

# Initialize Gemini Client
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def load_prompt() -> str:
    """Load the System Instruction from config file."""
    try:
        with open("data/config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("system_instruction", "You are Coach Dyno.")
    except FileNotFoundError:
        logger.warning("[COACH AGENT] config.json not found. Using default persona.")
        return "You are Coach Dyno, a strict running coach and data analyst."

# ==========================================
# DEFINING TOOLS FOR THE AGENT
# ==========================================
def tool_send_telegram(message: str) -> str:
    """
    Use this tool to send immediate alerts, warnings, or direct feedback to the User via Telegram.
    This MUST be called when the user violates training rules or asks a direct question.
    """
    logger.info(f">>> [TOOL EXECUTED] Sending Telegram message: {message}")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    success = send_telegram_msg(chat_id, message)
    return "Message sent successfully." if success else "Failed to send message."

def tool_analyze_run_data(activity_id: str) -> dict:
    """
    Use this tool to analyze raw Strava run data and extract key metrics 
    such as TRIMP (Training Impulse), average HR, and intensity level.
    """
    logger.info(f">>> [TOOL EXECUTED] Analyzing Activity ID: {activity_id}")
    
    # Placeholder for actual CSV fetching logic (to be integrated later)
    simulated_duration = 45.0
    simulated_hr = 165.0
    
    return calculate_trimp(duration_minutes=simulated_duration, avg_hr=simulated_hr)

# Initialize the Generative Model with tools
agent_model = genai.GenerativeModel(
    model_name='gemini-flash-latest',
    tools=[tool_send_telegram, tool_analyze_run_data],
    system_instruction=load_prompt()
)

# ==========================================
# AGENT WORKFLOWS
# ==========================================
def process_strava_run(activity_id: str):
    """Workflow triggered when a new run is completed."""
    logger.info("[COACH AGENT] Starting analysis for new run...")
    
    chat_session = agent_model.start_chat(enable_automatic_function_calling=True)
    
    prompt = f"""
    A new run activity (ID: {activity_id}) has been uploaded.
    Tasks:
    1. Call `tool_analyze_run_data` to calculate the training load metrics.
    2. Evaluate the metrics against the user's baseline (rFTP 315W) and current injury status (Achilles pain).
    3. If the run was too intense for a recovery day, IMMEDIATELY call `tool_send_telegram` to warn the user.
    4. Provide a short summary review to be updated on Strava description.
    """
    
    try:
        response = chat_session.send_message(prompt)
        final_review = response.text
        logger.info(f"[COACH AGENT] Final Review Generated:\n{final_review}")
        
        # TODO: Implement Strava PUT request here to update description
        
    except Exception as e:
        logger.error(f"[COACH AGENT] Error during processing: {e}")

def handle_telegram_chat(chat_id: str, text: str):
    """Workflow triggered when the user sends a message via Telegram."""
    logger.info("[COACH AGENT] Replying to User's Telegram message...")
    
    chat_session = agent_model.start_chat(enable_automatic_function_calling=True)
    
    prompt = f"""
    The user just sent you a direct message: '{text}'. 
    Analyze the context and use `tool_send_telegram` to reply directly to them.
    """
    
    try:
        chat_session.send_message(prompt)
    except Exception as e:
        logger.error(f"[COACH AGENT] Error during chat handling: {e}")