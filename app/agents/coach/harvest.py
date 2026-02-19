import os
import json
import logging

# --- MODULE IMPORTS ---
from app.agents.coach.strava_client import StravaClient
from app.core.database import save_message, init_db

# Initialize logger
logger = logging.getLogger("AI_COACH")

def harvest_data():
    """
    Harvests recent data and overall stats from Strava.
    Updates the local JSON stats file and injects recent runs into the AI's memory.
    """
    logger.info("[HARVEST] Starting Strava data harvest process...")
    
    # Ensure the database is initialized
    init_db()
    
    # Initialize the Strava API Client
    # It automatically picks up credentials from the environment variables
    strava_client = StravaClient()
    
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    athlete_id = os.getenv("STRAVA_ATHLETE_ID")

    if not chat_id or not athlete_id:
        logger.error("[HARVEST] Failed: Missing TELEGRAM_CHAT_ID or STRAVA_ATHLETE_ID in environment variables.")
        return

    # 1. Harvest Athlete Stats (YTD, Recent, Total)
    logger.info(f"[HARVEST] Fetching overall statistics for Athlete ID: {athlete_id}...")
    athlete_stats = strava_client.get_athlete_stats(athlete_id)
    
    if athlete_stats:
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
        stats_file_path = "data/athlete_stats.json"
        
        with open(stats_file_path, "w", encoding="utf-8") as file:
            json.dump(athlete_stats, file, indent=4)
            
        ytd_distance = athlete_stats.get('ytd_run_totals', 0)
        logger.info(f"[HARVEST] Stats updated successfully. YTD Distance: {ytd_distance:.1f} km.")

    # 2. Harvest Recent Activities (Last 10 runs)
    logger.info("[HARVEST] Fetching the 10 most recent activities...")
    recent_activities = strava_client.get_recent_activities(limit=10)
    
    loaded_count = 0
    # Process in reverse order (oldest first) to maintain correct chronological context in DB
    for activity in reversed(recent_activities):
        activity_type = activity.get('type')
        
        # Only process running activities
        if activity_type in ['Run', 'TrailRun', 'VirtualRun']:
            distance_km = activity.get('distance', 0) / 1000
            moving_time_sec = activity.get('moving_time', 0)
            
            # Calculate pace (minutes per km)
            if distance_km > 0:
                pace_decimal = (moving_time_sec / 60) / distance_km
                pace_minutes = int(pace_decimal)
                pace_seconds = int((pace_decimal % 1) * 60)
            else:
                pace_minutes, pace_seconds = 0, 0
            
            # Formulate the summary string (Vietnamese context for the AI to read naturally)
            activity_date = activity.get('start_date_local', '')[:10]
            activity_name = activity.get('name', 'Unknown Run')
            
            run_summary = (
                f"[HISTORICAL RUN] {activity_date} | {activity_name}\n"
                f"📏 Quãng đường: {distance_km:.2f} km\n"
                f"⚡ Pace: {pace_minutes}:{pace_seconds:02d} min/km"
            )
            
            # Inject into the conversational memory
            save_message(str(chat_id), "model", run_summary)
            loaded_count += 1
            logger.debug(f"[HARVEST] Injected activity into memory: {activity_name}")

    logger.info(f"[HARVEST] Harvest complete! {loaded_count} running activities injected into memory.")

if __name__ == "__main__":
    # This block is for manual script execution/testing only.
    # It explicitly loads the .env file since main.py is not running.
    from dotenv import load_dotenv
    load_dotenv()
    
    # Configure basic console logging for standalone execution
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    harvest_data()