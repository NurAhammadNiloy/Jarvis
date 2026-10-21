import sqlite3

# Connect to the database
conn = sqlite3.connect("data/memory.db")
cursor = conn.cursor()

# Retrieve all data from conversation_memory
print("Conversations:")
cursor.execute("SELECT * FROM conversation_memory;")
for row in cursor.fetchall():
    print(row)

# Retrieve all data from user_preferences
print("\nUser Preferences:")
cursor.execute("SELECT * FROM user_preferences;")
for row in cursor.fetchall():
    print(row)

# Retrieve all data from session_data
print("\nSession Data:")
cursor.execute("SELECT * FROM session_data;")
for row in cursor.fetchall():
    print(row)

conn.close()
