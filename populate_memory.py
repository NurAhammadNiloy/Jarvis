import sqlite3

# Path to the database
DB_PATH = "data/memory.db"

def populate_memory():
    """
    Populates the memory.db database with sample data for testing.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Insert a sample conversation into conversation_memory
    cursor.execute("""
        INSERT INTO conversation_memory (timestamp, user_query, jervis_response)
        VALUES 
            ('2024-12-06T16:00:00', 'What is the time?', 'The time is 4:00 PM.'),
            ('2024-12-06T16:05:00', 'What’s the weather in Helsinki?', 'It’s sunny in Helsinki.');
    """)

    # Insert a sample user preference into user_preferences
    cursor.execute("""
        INSERT INTO user_preferences (key, value)
        VALUES 
            ('default_location', 'Kokkola'),
            ('preferred_language', 'English');
    """)

    # Insert a sample session variable into session_data
    cursor.execute("""
        INSERT INTO session_data (key, value)
        VALUES 
            ('pending_hour', '5 PM');
    """)

    conn.commit()
    conn.close()
    print("Sample data added successfully!")

# Run the function
if __name__ == "__main__":
    populate_memory()
