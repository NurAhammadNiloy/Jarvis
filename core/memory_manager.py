from collections import deque
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "data/memory.db"
FLAGGED_CLEANUP_THRESHOLD = 30
MAX_DELETE_BATCH = 20
GRACE_PERIOD_DAYS = 2

short_term_memory = deque(maxlen=5)

def add_to_short_term_memory(user_query, jervis_response):
    if not user_query.strip() or "I didn't catch that" in jervis_response:
        print("Skipping uninformative response.")
        return
    if user_query in [entry[0] for entry in short_term_memory]:
        print("Duplicate query detected. Skipping addition.")
        return
    short_term_memory.appendleft((user_query, jervis_response))
    print(f"Added to memory: {user_query} -> {jervis_response}")

def get_recent_short_term():
    return list(short_term_memory)

def initialize_memory():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_query TEXT NOT NULL,
                jervis_response TEXT NOT NULL,
                flagged BOOLEAN DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_data (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()
        print("Database and tables are ready.")
    except sqlite3.Error as e:
        print(f"Error initializing memory: {e}")
    finally:
        if conn:
            conn.close()

def store_conversation(user_query, jervis_response, flagged=0):
    add_to_short_term_memory(user_query, jervis_response)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversation_memory (timestamp, user_query, jervis_response, flagged)
            VALUES (datetime('now'), ?, ?, ?)
        """, (user_query, jervis_response, flagged))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error storing conversation: {e}")
    finally:
        if conn:
            conn.close()

def get_recent_conversations(limit=5):
    """Get recent conversations from short-term memory, fallback to database."""
    short_term = get_recent_short_term()
    if short_term:
        return short_term
    
    # Fallback to database if short-term is empty (e.g., after restart)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_query, jervis_response
            FROM conversation_memory
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        return results
    except sqlite3.Error as e:
        print(f"Error retrieving conversations: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_all_conversations(limit=50):
    """Retrieve conversation history from database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, user_query, jervis_response, flagged
            FROM conversation_memory
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Error retrieving all conversations: {e}")
        return []
    finally:
        if conn:
            conn.close()

def set_user_preference(key, value):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_preferences (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error setting user preference: {e}")
    finally:
        if conn:
            conn.close()

def get_user_preference(key):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM user_preferences WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        print(f"Error retrieving user preference: {e}")
        return None
    finally:
        if conn:
            conn.close()

def set_session_data(key, value):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO session_data (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error setting session data: {e}")
    finally:
        if conn:
            conn.close()

def get_session_data(key):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM session_data WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        print(f"Error retrieving session data: {e}")
        return None
    finally:
        if conn:
            conn.close()

def cleanup_conversation_memory():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM conversation_memory WHERE flagged = 0")
        total_flag_0 = cursor.fetchone()[0]
        if total_flag_0 >= FLAGGED_CLEANUP_THRESHOLD:
            print(f"Total flag=0 entries ({total_flag_0}) exceed threshold ({FLAGGED_CLEANUP_THRESHOLD}). Initiating cleanup...")
            cursor.execute("""
                 DELETE FROM conversation_memory
                 WHERE id IN (
                     SELECT id FROM conversation_memory
                     WHERE flagged = 0
                     ORDER BY timestamp ASC
                     LIMIT ?
                    )
            """, (MAX_DELETE_BATCH,))
            conn.commit()
            print(f"Cleanup completed: {MAX_DELETE_BATCH} old unflagged conversations removed.")
            cutoff_date = (datetime.now() - timedelta(days=GRACE_PERIOD_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                DELETE FROM conversation_memory
                WHERE flagged = 0 AND timestamp < ?
            """, (cutoff_date,))
            conn.commit()
            print(f"Cleanup completed: Executed reminders older than the grace period of {GRACE_PERIOD_DAYS} days removed.")
    except sqlite3.Error as e:
        print(f"Error during cleanup: {e}")
    finally:
        if conn:
            conn.close()

def get_contextual_memory(topic, limit=3):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_query, jervis_response
            FROM conversation_memory
            WHERE user_query LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f"%{topic}%", limit))
        results = cursor.fetchall()
        return results
    except sqlite3.Error as e:
        print(f"Error retrieving context: {e}")
        return []
    finally:
        if conn:
            conn.close()

