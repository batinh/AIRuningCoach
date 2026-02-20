import sqlite3
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger("AI_COACH")
DB_PATH = "data/os_core.db"  # Đổi tên file để đánh dấu kỷ nguyên mới (Multi-Tenant)

def get_db_connection():
    """Helper function to get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Trả về kết quả dưới dạng dict thay vì tuple
    return conn

def init_db():
    """Initialize the relational database schema."""
    os.makedirs("data", exist_ok=True)
    conn = get_db_connection()
    c = conn.cursor()
  
    # 1. Table: users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            max_hr INTEGER DEFAULT 185,
            rest_hr INTEGER DEFAULT 55,
            race_date TEXT,
            current_goal TEXT,
            is_active BOOLEAN DEFAULT 1
        )
    ''')

# 2. Table: run_activities
    c.execute('''
        CREATE TABLE IF NOT EXISTS run_activities (
            activity_id TEXT PRIMARY KEY,
            user_id TEXT,
            name TEXT,
            start_date DATETIME,
            distance_km REAL,
            moving_time_min REAL,
            avg_hr INTEGER,
            max_hr INTEGER,
            suffer_score INTEGER,
            trimp_score REAL,
            gcs_score INTEGER DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # [NEW] Auto-migrate: Thêm cột gcs_score cho DB cũ nếu chưa có
    try:
        c.execute("ALTER TABLE run_activities ADD COLUMN gcs_score INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass # Bỏ qua nếu cột đã tồn tại

    # 3. Table: chat_history (Upgraded)
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("[DATABASE] Relational DB initialized successfully (Multi-Tenant Ready).")

# ==========================================
# USERS CRUD
# ==========================================
def upsert_user(user_id: str, name: str = "Runner", max_hr: int = 185, rest_hr: int = 55):
    """Insert a new user or update existing user."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (user_id, name, max_hr, rest_hr)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                max_hr=excluded.max_hr,
                rest_hr=excluded.rest_hr
        ''', (str(user_id), name, max_hr, rest_hr))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[DB_ERROR] Failed to upsert user: {e}")

def get_user(user_id: str) -> Optional[Dict]:
    """Retrieve user physiology profile."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"[DB_ERROR] Failed to get user: {e}")
        return None

# ==========================================
# RUN ACTIVITIES CRUD
# ==========================================
def save_run_activity(user_id: str, activity_data: Dict):
    """Save a detailed run activity for scientific calculation."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Lấy GCS cũ nếu có để không bị mất điểm khi chạy Sync ghi đè
        c.execute("SELECT gcs_score FROM run_activities WHERE activity_id = ?", (str(activity_data['activity_id']),))
        row = c.fetchone()
        existing_gcs = row['gcs_score'] if row else None

        c.execute('''
            INSERT OR REPLACE INTO run_activities 
            (activity_id, user_id, name, start_date, distance_km, moving_time_min, avg_hr, max_hr, suffer_score, trimp_score, gcs_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(activity_data['activity_id']),
            str(user_id),
            activity_data.get('name', 'Untitled'),
            activity_data.get('start_date'),
            activity_data.get('distance_km', 0),
            activity_data.get('moving_time_min', 0),
            activity_data.get('avg_hr', 0),
            activity_data.get('max_hr', 0),
            activity_data.get('suffer_score', 0),
            activity_data.get('trimp_score', 0.0),
            existing_gcs
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[DB_ERROR] Failed to save run activity: {e}")

def update_run_gcs_score(activity_id: str, gcs_score: int):
    """Cập nhật điểm GCS sau khi AI phân tích xong."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE run_activities SET gcs_score = ? WHERE activity_id = ?", (gcs_score, str(activity_id)))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[DB_ERROR] Failed to update GCS: {e}")
# ==========================================
# CHAT HISTORY CRUD
# ==========================================
def save_message(user_id: str, role: str, text: str):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", 
                  (str(user_id), role, text))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[DB_ERROR] Save Message Error: {e}")

def load_history_for_gemini(user_id: str, limit: int = 20) -> List[Dict]:
    """Load conversation history for the AI Agent."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", 
                  (str(user_id), limit))
        rows = c.fetchall()
        conn.close()
        
        history = []
        for row in reversed(rows):
            history.append({"role": row['role'], "parts": [row['content']]})
        return history
    except Exception as e:
        logger.error(f"[DB_ERROR] Load History Error: {e}")
        return []

def clear_history(user_id: str):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM chat_history WHERE user_id = ?", (str(user_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[DB_ERROR] Clear History Error: {e}")
# ==========================================
# ADVANCED ANALYTICS (AI QUERIES)
# ==========================================
def get_training_loads(user_id: str) -> dict:
    """Calculate Acute (7d) and Chronic (28d) load based on TRIMP from DB."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Acute Load (Tổng TRIMP 7 ngày qua)
        c.execute('''
            SELECT SUM(trimp_score) as acute_load 
            FROM run_activities 
            WHERE user_id = ? AND start_date >= date('now', '-7 days')
        ''', (str(user_id),))
        acute = c.fetchone()['acute_load']
        acute = round(acute, 2) if acute else 0.0

        # Chronic Load (Tổng TRIMP 28 ngày qua)
        c.execute('''
            SELECT SUM(trimp_score) as chronic_load 
            FROM run_activities 
            WHERE user_id = ? AND start_date >= date('now', '-28 days')
        ''', (str(user_id),))
        chronic = c.fetchone()['chronic_load']
        chronic = round(chronic, 2) if chronic else 0.0
        
        conn.close()
        return {"acute_load_7d": acute, "chronic_load_28d": chronic}
    except Exception as e:
        logger.error(f"[DB_ERROR] Failed to get training loads: {e}")
        return {"acute_load_7d": 0.0, "chronic_load_28d": 0.0}

def get_recent_runs_log(user_id: str, limit: int = 5) -> str:
    """Get a formatted string of recent runs for the AI prompt."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            SELECT start_date, name, distance_km, trimp_score, gcs_score 
            FROM run_activities 
            WHERE user_id = ? 
            ORDER BY start_date DESC LIMIT ?
        ''', (str(user_id), limit))
        rows = c.fetchall()
        conn.close()
        
        if not rows: return "No recent runs found in database."
        
        log_lines = []
        for r in rows:
            date_str = r['start_date'][:10]
            gcs_text = f" | GCS: {r['gcs_score']}%" if r['gcs_score'] is not None else ""
            log_lines.append(f"- {date_str}: {r['name']} | {r['distance_km']}km | TRIMP Load: {r['trimp_score']}{gcs_text}")
        return "\n".join(log_lines)
    except Exception as e:
        logger.error(f"[DB_ERROR] Failed to get recent runs: {e}")
        return "Error loading recent runs."