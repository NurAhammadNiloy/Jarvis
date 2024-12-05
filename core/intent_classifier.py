def classify_intent(query):
    if "remind" in query:
        return "reminder"
    elif "weather" in query:
        return "weather"
    elif "thank" in query:
        return "thank"
    elif "time" in query:
        return "time"
    elif "date" in query:
        return "date"
    elif "youtube" in query:
        return "youtube"
    elif "google" in query:
        return "google"
    elif "status" in query:
        return "status"
    elif "what you are doing" in query:
        return "what you are doing"
    else:
        return "chat"
