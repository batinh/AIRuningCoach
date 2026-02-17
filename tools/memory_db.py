import sqlite3
import os
import logging

logger = logging.getLogger(__name__)
DB_PATH = "data/coach_memory.db"

def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (chat_id TEXT, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def save_message(chat_id, role, text):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO chat_history (chat_id, role, content) VALUES (?, ?, ?)", 
                  (str(chat_id), role, text))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Save Error: {e}")

def load_history_for_gemini(chat_id, limit=20):
    """Hàm này cực kỳ quan trọng để Agent có trí nhớ"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT role, content FROM chat_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?", 
                  (str(chat_id), limit))
        rows = c.fetchall()
        conn.close()
        
        history = []
        for role, content in reversed(rows):
            history.append({"role": role, "parts": [content]})
        return history
    except Exception as e:
        logger.error(f"DB Load Error: {e}")
        return []

def clear_history(chat_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM chat_history WHERE chat_id = ?", (str(chat_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Clear Error: {e}")