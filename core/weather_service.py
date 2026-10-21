import requests
import geocoder
from datetime import datetime
from config.api_keys import WEATHER_API_KEY, GOOGLE_API_KEY

def get_user_location():
    try:
        g = geocoder.ip('me')
        if g.ok and g.city:
            return g.city
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def get_precise_location():
    url = f'https://www.googleapis.com/geolocation/v1/geolocate?key={GOOGLE_API_KEY}'
    try:
        response = requests.post(url, json={})
        if response.status_code == 200:
            location_data = response.json()
            latitude = location_data['location']['lat']
            longitude = location_data['location']['lng']
            return latitude, longitude
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None

def get_city_from_coordinates(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&addressdetails=1"
    headers = {
        "User-Agent": "JarvisAssistant/1.0"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            city = data.get("address", {}).get("city", "")
            if not city:
                city = data.get("address", {}).get("town", "")
            if not city:
                city = data.get("address", {}).get("village", "")
            if not city:
                city = data.get("address", {}).get("municipality", "")
            return city
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None

def _format_temperature(temperature):
    """Format temperature with proper grammar."""
    if -0.5 < temperature < 0.5:
        return "0 degrees"
    elif abs(round(temperature)) == 1:
        return f"{round(temperature)} degree"
    else:
        return f"{round(temperature)} degrees"

def _get_feels_like_description(actual, feels_like):
    """Describe the 'feels like' temperature difference."""
    diff = feels_like - actual
    if abs(diff) < 2:
        return ""
    elif diff < -5:
        return f", but it feels much colder at {_format_temperature(feels_like)} due to wind chill"
    elif diff < -2:
        return f", feels like {_format_temperature(feels_like)}"
    elif diff > 5:
        return f", but it feels much warmer at {_format_temperature(feels_like)}"
    elif diff > 2:
        return f", feels like {_format_temperature(feels_like)}"
    return ""

def _get_wind_description(wind_speed):
    """Get a human-friendly wind description."""
    if wind_speed < 1:
        return "calm"
    elif wind_speed < 4:
        return "a light breeze"
    elif wind_speed < 8:
        return "a moderate breeze"
    elif wind_speed < 14:
        return "quite windy"
    elif wind_speed < 20:
        return "very windy"
    else:
        return "extremely windy with strong gusts"

def _get_humidity_comment(humidity, temperature):
    """Get humidity-related comfort comment."""
    if humidity > 80 and temperature > 20:
        return " The humidity is high, so it might feel muggy."
    elif humidity < 30:
        return " The air is quite dry."
    return ""

def _get_time_of_day():
    """Get current time of day for contextual responses."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"

def _get_activity_suggestion(weather, temperature, wind_speed, is_daytime):
    """Suggest activities based on current conditions."""
    if temperature <= -15:
        return "Perfect weather for a warm drink and a good book indoors."
    elif temperature <= -5:
        if "clear" in weather or "snow" in weather:
            return "Great for a quick winter walk if you're bundled up!"
        return "A cozy day to stay warm inside."
    elif temperature <= 5:
        if "rain" in weather:
            return "Good weather for indoor activities."
        return "Nice for a brisk walk with a warm jacket."
    elif 15 <= temperature <= 25:
        if "clear" in weather and is_daytime:
            return "Perfect weather for outdoor activities!"
        elif "cloud" in weather:
            return "Great for a walk or outdoor exercise."
        elif "rain" in weather:
            return "Maybe save the outdoor plans for later."
    elif temperature > 25:
        if is_daytime:
            return "Stay hydrated if you're heading out."
        return "A pleasant evening to be outside."
    return ""

def _get_clothing_suggestion(temperature, weather, wind_speed):
    """Suggest appropriate clothing."""
    suggestions = []
    
    if temperature <= -20:
        suggestions = ["thermal layers", "a heavy winter coat", "insulated boots", "gloves", "a warm hat", "a scarf covering your face"]
    elif temperature <= -10:
        suggestions = ["multiple layers", "a warm winter coat", "warm boots", "gloves", "a hat"]
    elif temperature <= 0:
        suggestions = ["a winter jacket", "warm layers", "gloves"]
    elif temperature <= 10:
        suggestions = ["a warm jacket or coat"]
    elif temperature <= 18:
        suggestions = ["a light jacket or sweater"]
    elif temperature > 28:
        suggestions = ["light, breathable clothing"]
    
    if "rain" in weather and temperature > 0:
        suggestions.append("an umbrella")
    if "snow" in weather:
        suggestions.append("waterproof boots")
    if wind_speed > 10 and temperature < 10:
        suggestions.append("a windbreaker")
    
    if not suggestions:
        return ""
    elif len(suggestions) == 1:
        return f"I'd recommend {suggestions[0]}."
    else:
        return f"I'd recommend {', '.join(suggestions[:-1])}, and {suggestions[-1]}."

def get_weather(city, detailed=False, question_context=None):
    """Get comprehensive weather information for a city.
    
    Args:
        city: City name
        detailed: Whether to include full details
        question_context: Type of question asked ('go_outside', 'clothing', 'temperature')
    """
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": WEATHER_API_KEY,
        "units": "metric"
    }

    try:
        response = requests.get(base_url, params=params)
        if response.status_code == 200:
            data = response.json()
            
            # Extract all weather data
            temperature = data["main"]["temp"]
            feels_like = data["main"]["feels_like"]
            weather = data["weather"][0]["description"]
            weather_main = data["weather"][0]["main"].lower()
            wind_speed = data["wind"]["speed"]
            humidity = data["main"]["humidity"]
            visibility = data.get("visibility", 10000) / 1000  # Convert to km
            clouds = data.get("clouds", {}).get("all", 0)
            
            # Sunrise/sunset for day/night detection
            sunrise = data["sys"].get("sunrise", 0)
            sunset = data["sys"].get("sunset", 0)
            current_time = datetime.now().timestamp()
            is_daytime = sunrise < current_time < sunset
            
            time_of_day = _get_time_of_day()
            temp_text = _format_temperature(temperature)
            feels_like_text = _get_feels_like_description(temperature, feels_like)
            clothing = _get_clothing_suggestion(temperature, weather, wind_speed)
            
            # BRIEF MODE - concise response
            if not detailed:
                if temperature <= -15:
                    return f"It's extremely cold in {city}. {temp_text}{feels_like_text}, {weather}."
                elif temperature <= -5:
                    return f"Very cold in {city}. {temp_text}{feels_like_text}, {weather}."
                elif temperature <= 0:
                    return f"Freezing in {city}. {temp_text}, {weather}."
                elif temperature <= 10:
                    return f"It's cool in {city}. {temp_text}, {weather}."
                elif temperature <= 20:
                    return f"Mild weather in {city}. {temp_text}, {weather}."
                elif temperature <= 28:
                    return f"Pleasant {temp_text} in {city}, {weather}."
                else:
                    return f"It's hot in {city}. {temp_text}, {weather}."
            
            # DETAILED MODE - full response with suggestions
            parts = []
            
            # Contextual opener based on question type
            if question_context == "go_outside":
                # "Should I go outside?" - Direct answer first
                if temperature <= -15:
                    parts.append(f"Well sir, I wouldn't recommend it right now.")
                elif temperature <= -5:
                    parts.append(f"Well sir, only if you bundle up really well.")
                elif temperature <= 5:
                    parts.append(f"Well sir, you can, but dress warmly.")
                elif 15 <= temperature <= 25 and "rain" not in weather:
                    parts.append(f"Absolutely sir, it's lovely outside!")
                elif "rain" in weather or "storm" in weather:
                    parts.append(f"Well sir, I'd wait a bit - the weather isn't ideal.")
                else:
                    parts.append(f"Well sir, it's decent outside.")
            elif question_context == "clothing":
                # "What should I wear?" - Lead with clothing
                parts.append(f"Well sir, for {city} right now,")
                if clothing:
                    parts.append(clothing)
            elif question_context == "temperature":
                # "How cold/hot is it?" - Temperature focused
                parts.append(f"Well sir, it's {temp_text} in {city}{feels_like_text}.")
            
            # Weather details (skip the intro if we already have a contextual opener)
            if question_context:
                # Add condensed weather info after contextual opener
                parts.append(f"It's {temp_text} in {city}{feels_like_text}, with {weather}.")
            elif temperature <= -20:
                parts.append(f"Sir, it's dangerously cold in {city} right now. {temp_text}{feels_like_text}.")
                parts.append(f"Current conditions: {weather}.")
                parts.append("I strongly advise staying indoors unless absolutely necessary.")
            elif temperature <= -10:
                parts.append(f"It's very cold in {city} this {time_of_day}. {temp_text}{feels_like_text}, with {weather}.")
            elif temperature <= 0:
                parts.append(f"Freezing temperatures in {city}. Currently {temp_text}{feels_like_text}, with {weather}.")
            elif temperature <= 10:
                parts.append(f"It's quite cool in {city}. {temp_text}{feels_like_text}, with {weather}.")
            elif temperature <= 20:
                if "clear" in weather or "sun" in weather:
                    parts.append(f"Lovely weather in {city} this {time_of_day}! {temp_text} with {weather}.")
                else:
                    parts.append(f"Mild conditions in {city}. {temp_text} with {weather}.")
            elif temperature <= 28:
                parts.append(f"Warm weather in {city}! {temp_text} with {weather}.")
            else:
                parts.append(f"It's hot in {city} today. {temp_text}{feels_like_text}, with {weather}.")
            
            # Wind information (if notable)
            if wind_speed >= 4:
                wind_desc = _get_wind_description(wind_speed)
                parts.append(f"It's {wind_desc} at {round(wind_speed)} meters per second.")
            
            # Visibility warning
            if visibility < 1:
                parts.append("Visibility is very poor - please be careful if driving.")
            elif visibility < 5:
                parts.append("Visibility is somewhat reduced.")
            
            # Humidity comment
            humidity_comment = _get_humidity_comment(humidity, temperature)
            if humidity_comment:
                parts.append(humidity_comment.strip())
            
            # Clothing suggestion (skip if already added for clothing context)
            if question_context != "clothing" and clothing:
                parts.append(clothing)
            
            # Activity suggestion
            activity = _get_activity_suggestion(weather, temperature, wind_speed, is_daytime)
            if activity:
                parts.append(activity)
            
            # Detailed mode - add extra info
            if detailed:
                parts.append(f"Humidity is at {humidity}%, and cloud cover is {clouds}%.")
            
            return " ".join(parts)

        elif response.status_code == 404:
            return f"I couldn't find weather data for {city}. Could you check the spelling?"
        elif response.status_code == 401:
            return "There's an issue with the weather service authentication. Please check the API key."
        else:
            return f"I encountered an issue getting the weather: {response.status_code}. Let me try again later."
    except requests.exceptions.RequestException as e:
        return "I'm having trouble connecting to the weather service right now. Please try again in a moment."

def get_forecast(city, days=3):
    """Get weather forecast for upcoming days."""
    base_url = "http://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city,
        "appid": WEATHER_API_KEY,
        "units": "metric",
        "cnt": days * 8  # API returns 3-hour intervals
    }
    
    try:
        response = requests.get(base_url, params=params)
        if response.status_code == 200:
            data = response.json()
            
            # Group by day
            daily_data = {}
            for item in data["list"]:
                date = datetime.fromtimestamp(item["dt"]).strftime("%A")
                if date not in daily_data:
                    daily_data[date] = {
                        "temps": [],
                        "weather": [],
                        "wind": []
                    }
                daily_data[date]["temps"].append(item["main"]["temp"])
                daily_data[date]["weather"].append(item["weather"][0]["description"])
                daily_data[date]["wind"].append(item["wind"]["speed"])
            
            # Build conversational forecast
            days_list = list(daily_data.items())[:days]
            
            if not days_list:
                return f"I couldn't get forecast data for {city}."
            
            parts = [f"Sir, here's the outlook for {city}."]
            
            for i, (day, info) in enumerate(days_list):
                min_temp = round(min(info["temps"]))
                max_temp = round(max(info["temps"]))
                weather = max(set(info["weather"]), key=info["weather"].count)
                avg_wind = sum(info["wind"]) / len(info["wind"])
                
                # Make it conversational based on conditions
                if i == 0:
                    day_word = "Today" if datetime.now().strftime("%A") == day else day
                else:
                    day_word = day
                
                # Temperature description
                if max_temp <= -15:
                    temp_feel = "dangerously cold"
                elif max_temp <= -5:
                    temp_feel = "very cold"
                elif max_temp <= 5:
                    temp_feel = "quite chilly"
                elif max_temp <= 15:
                    temp_feel = "cool"
                elif max_temp <= 25:
                    temp_feel = "pleasant"
                else:
                    temp_feel = "warm"
                
                # Weather advice
                if "snow" in weather:
                    weather_note = "expect some snow"
                elif "rain" in weather:
                    weather_note = "bring an umbrella"
                elif "clear" in weather:
                    weather_note = "skies will be clear"
                elif "cloud" in weather:
                    weather_note = "it'll be cloudy"
                else:
                    weather_note = weather
                
                # Build the day's forecast naturally
                if min_temp == max_temp:
                    temp_text = f"around {min_temp} degrees"
                else:
                    temp_text = f"between {min_temp} and {max_temp} degrees"
                
                parts.append(f"{day_word} will be {temp_feel}, {temp_text}, and {weather_note}.")
            
            # Add overall advice
            coldest = min(min(info["temps"]) for _, info in days_list)
            if coldest <= -10:
                parts.append("Bundle up warmly if you're heading out this week!")
            elif any("rain" in max(set(info["weather"]), key=info["weather"].count) for _, info in days_list):
                parts.append("Keep an umbrella handy!")
            elif any("snow" in max(set(info["weather"]), key=info["weather"].count) for _, info in days_list):
                parts.append("Looks like we'll have some winter weather!")
            
            return " ".join(parts)
        else:
            return f"I couldn't get the forecast for {city}, sir."
    except requests.exceptions.RequestException:
        return "I'm having trouble getting the forecast right now, sir."

def compare_weather(city1, city2):
    """Compare weather between two cities."""
    weather1 = get_weather(city1)
    weather2 = get_weather(city2)
    
    # Get raw data for comparison
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    try:
        data1 = requests.get(base_url, params={"q": city1, "appid": WEATHER_API_KEY, "units": "metric"}).json()
        data2 = requests.get(base_url, params={"q": city2, "appid": WEATHER_API_KEY, "units": "metric"}).json()
        
        temp1 = data1["main"]["temp"]
        temp2 = data2["main"]["temp"]
        diff = abs(temp1 - temp2)
        
        if temp1 > temp2:
            comparison = f"{city1} is {_format_temperature(diff)} warmer than {city2}."
        elif temp2 > temp1:
            comparison = f"{city2} is {_format_temperature(diff)} warmer than {city1}."
        else:
            comparison = f"Both cities are at the same temperature."
        
        return f"{city1}: {_format_temperature(temp1)} with {data1['weather'][0]['description']}. " \
               f"{city2}: {_format_temperature(temp2)} with {data2['weather'][0]['description']}. " \
               f"{comparison}"
    except:
        return f"I couldn't compare the weather between {city1} and {city2}."
