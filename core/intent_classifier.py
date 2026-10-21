def classify_intent(query):
    query_lower = query.lower()
    
    if "remind" in query_lower:
        return "reminder"
    
    # Timer intent - includes status queries, pause/resume, etc.
    elif "timer" in query_lower:
        return "timer"
    elif "pomodoro" in query_lower:
        return "timer"
    elif ("set" in query_lower or "start" in query_lower) and ("minute" in query_lower or "second" in query_lower or "hour" in query_lower):
        return "timer"
    # Timer status queries - check for time remaining patterns BEFORE the "time" intent
    elif ("how much" in query_lower or "how long" in query_lower) and ("left" in query_lower or "remaining" in query_lower):
        return "timer"
    elif "time left" in query_lower or "time remaining" in query_lower:
        return "timer"
    elif "pause" in query_lower and any(w in query_lower for w in ["timer", "it", "that", "the"]):
        return "timer"
    elif "resume" in query_lower:
        return "timer"
    # "start the timer again", "start it again", etc.
    elif "start" in query_lower and "again" in query_lower:
        return "timer"
    elif "unpause" in query_lower or "continue" in query_lower:
        return "timer"
    
    elif "alarm" in query_lower:
        return "alarm"
    elif "forecast" in query_lower or "week" in query_lower and "weather" in query_lower:
        return "forecast"
    elif ("weather" in query_lower or 
          "should i go" in query_lower or 
          "can i go outside" in query_lower or 
          "go outside" in query_lower or
          "should i wear" in query_lower or 
          "what should i wear" in query_lower or 
          "what to wear" in query_lower or
          "how cold" in query_lower or 
          "how hot" in query_lower or 
          "temperature" in query_lower or
          "is it cold" in query_lower or
          "is it hot" in query_lower or
          "is it warm" in query_lower):
        return "weather"
    elif "thank" in query_lower:
        return "thank"
    elif "time" in query_lower:
        return "time"
    elif "date" in query_lower:
        return "date"
    elif "play" in query_lower or "youtube" in query_lower:
        return "youtube"
    elif "open google" in query_lower or query_lower == "google":
        return "google"
    elif "status" in query_lower:
        return "status"
    elif "what you are doing" in query_lower:
        return "what you are doing"
    else:
        return "chat"
