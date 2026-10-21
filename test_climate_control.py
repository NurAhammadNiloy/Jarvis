import socketio

# Create a Socket.IO client
sio = socketio.Client()

# Event: Connection established
@sio.event
def connect():
    print("Connected to the server.")

# Event: Connection lost
@sio.event
def disconnect():
    print("Disconnected from the server.")

# Event: Handle real-time alerts
@sio.on("alert")
def handle_alert(data):
    alert_type = data.get("type", "unknown").upper()
    message = data.get("message", "No message provided")
    print(f"[ALERT] {alert_type}: {message}")

# Connect to the server at localhost
try:
    sio.connect("http://127.0.0.1:5000")  # Use 192.168.1.108:5000 if accessing from another device in your network
    print("Listening for real-time alerts...")
    sio.wait()  # Keep the connection open to listen for events
except Exception as e:
    print(f"Failed to connect to the server: {e}")
