import requests
import geocoder
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
        "User-Agent": "YourAppName/1.0 (contact@yourdomain.com)"  # Replace with your app name and contact info
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

def get_weather(city, detailed=False):
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
            temperature = data["main"]["temp"]
            weather = data["weather"][0]["description"]
            wind_speed = data["wind"]["speed"]
            humidity = data["main"]["humidity"]

            # Handle temperature output:
            if -0.5 < temperature < 0.5:  # For temperatures around 0°C
                temperature_text = "0 degree Celsius"
            elif abs(temperature) == 1:  # Singular form for 1 or -1 degree Celsius
                temperature_text = "1 degree Celsius"
            else:  # For other temperatures, round to nearest whole number and use "degrees"
                temperature_text = f"{round(temperature)} degrees Celsius"

            # Checking for rain and snow intensities
            rain_intensity = data.get("rain", {}).get("1h", 0)
            snow_intensity = data.get("snow", {}).get("1h", 0)

            # Proactive suggestions based on weather conditions
            if "clear" in weather:
                response_text = f"Looks like a sunny day in {city} with a pleasant {temperature_text}. Perfect for outdoor activities!"
            elif "cloud" in weather:
                response_text = f"The skies are cloudy in {city} with a temperature of {temperature_text}. A good day to stay cozy inside or go for a walk!"
            elif "snow" in weather:
                if snow_intensity >= 5:  # Heavy snow
                    response_text = f"Heavy snow in {city} today with a chilly {temperature_text}. It might be a good idea to bundle up and stay warm. Be careful on the roads!"
                elif snow_intensity > 0:  # Light snow
                    response_text = f"Light snow in {city} with a temperature of {temperature_text}. A good day to enjoy the snow but stay warm!"
                else:
                    response_text = f"Snow in {city} with a chilly {temperature_text}. Stay warm and cautious if you're heading out."
            elif "rain" in weather:
                if rain_intensity >= 3:  # Heavy rain
                    response_text = f"Heavy rain in {city} with a temperature of {temperature_text}. Don’t forget your umbrella and stay dry!"
                elif rain_intensity > 0:  # Light rain
                    response_text = f"Light rain in {city} with a temperature of {temperature_text}. You might want to bring an umbrella."
                else:
                    response_text = f"The weather in {city} is rainy with a temperature of {temperature_text}."
            elif "fog" in weather:
                response_text = f"Foggy conditions in {city} with {temperature_text}. Take extra care while driving or walking around."
            else:
                response_text = f"The weather in {city} is currently {weather} with a temperature of {temperature_text}."

            # Proactive suggestions for cold and snowy conditions
            if temperature <= -5:
                response_text += " It's quite cold outside! Make sure to dress warmly with gloves and a scarf."

            # Optional detailed weather info
            if detailed:
                response_text += f" Wind speed is {wind_speed} m/s and the humidity is {humidity}%. Would you like to know anything else about the weather?"

            return response_text

        elif response.status_code == 404:
            return f"Oops! I couldn't find the weather for {city}. Maybe check the spelling or try another city."
        elif response.status_code == 401:
            return "I’m having trouble connecting to the weather service. Could you check if the API key is valid?"
        else:
            return f"An unexpected error occurred: {response.status_code} - {response.reason}. Let me try again later."
    except requests.exceptions.RequestException as e:
        return "It seems like there’s an issue connecting to the weather service. I'll try again shortly!"
