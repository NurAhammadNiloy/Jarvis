from core.speech_synthesis import synthesize_speech
from core.weather_service import get_weather, get_user_location, get_precise_location, get_city_from_coordinates
from core.reminder_manager import handle_reminder, get_reminders, delete_reminder
from core.chatgpt_service import get_chatgpt_response
from core.youtube_service import search_youtube
import webbrowser
from datetime import datetime
from core.intent_classifier import classify_intent
import random

def handle_query(query):
    intent = classify_intent(query)

    if intent == "reminder":
        # Process reminder setting logic (as previously implemented)
        handle_reminder(query)
        return True

    elif "what are my reminders" in query.lower() or "tell me my reminders" in query.lower():
        get_reminders()
        return True

    elif intent == "weather":
        # Try to get the city from the query or fall back to user's location
        city = query.replace("weather", "").strip() or get_user_location()

        if not city or city.lower() != "kokkola":  # Replace "kokkola" with your desired location check if needed
            coords = get_precise_location()  # Get latitude and longitude
            if coords:
                city = get_city_from_coordinates(*coords)

        if city:
            weather_info = get_weather(city)
            synthesize_speech(weather_info)
        else:
            synthesize_speech("I couldn't determine your location. Please tell me the city for the weather update.")
        return True

    elif intent == "youtube" or "open a video" in query.lower() or "show me a video" in query.lower():
        # Extract the topic for the video
        topic = query.replace("open a video about", "").replace("show me a video about", "").strip()
        video_url = search_youtube(query)

        if video_url:
            webbrowser.open(video_url)
            if topic:
                synthesize_speech(f"Opening a video about {topic}.")
            else:
                synthesize_speech("Opening YouTube.")
        else:
            synthesize_speech("Couldn't find a video for that.")
        return True

    elif intent == "time":
        current_time = datetime.now().strftime("%I:%M %p")
        synthesize_speech(f"The current time is {current_time}.")
        return True

    elif intent == "date":
        current_date = datetime.now().strftime("%B %d, %Y")
        synthesize_speech(f"Today's date is {current_date}.")
        return True

    elif intent == "google":
        webbrowser.open("https://www.google.com")
        synthesize_speech("Opening Google.")
        return True

    elif intent == "status":
        synthesize_speech("All systems are fully operational, sir.")
        return True
    elif intent == "thank":
        responses = [
        "You're welcome, boss. Always here to assist.",
        "Of course, boss. Let me know if there's anything else.",
        "No problem at all, boss. I'm happy to help.",
        "Absolutely, boss. Your wish is my command.",
        "As always, boss, it's my pleasure."
        ]
        synthesize_speech(random.choice(responses))
        return True
    
    elif intent == "what you are doing":
        responses = [
         "Just here, ready to assist you, boss.",
         "Monitoring the system. Let me know if you need anything.",
         "Keeping an eye on things. What can I do for you?"
        ]
        synthesize_speech(random.choice(responses))
        return True


    else:
        response = get_chatgpt_response(query)
        synthesize_speech(response)
        return True  # Ensure this confirms the response has been handled

    # If no condition was met, return False for fallback logic
    return False
