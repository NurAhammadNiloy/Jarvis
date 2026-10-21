import sqlite3

# Path to the database
DB_PATH = "data/memory.db"

def clear_memory():
    """
    Deletes all data from the memory database for testing or resetting purposes.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Clear all rows from conversation_memory
    cursor.execute("DELETE FROM conversation_memory;")
    print("Cleared conversation_memory.")

    # Clear all rows from user_preferences
    cursor.execute("DELETE FROM user_preferences;")
    print("Cleared user_preferences.")

    # Clear all rows from session_data
    cursor.execute("DELETE FROM session_data;")
    print("Cleared session_data.")

    conn.commit()
    conn.close()
    print("Memory database cleaned successfully!")

# Run the function
if __name__ == "__main__":
    clear_memory()
