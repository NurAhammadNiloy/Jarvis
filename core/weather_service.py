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
            response_text = f"The weather in {city} is currently {weather} with a temperature of {temperature}°C."
            return response_text
        elif response.status_code == 404:
            return "The city was not found. Please check the city name and try again."
        elif response.status_code == 401:
            return "There was an issue with the API key. Please check if it's valid."
        else:
            return f"An error occurred: {response.status_code} - {response.reason}"
    except requests.exceptions.RequestException as e:
        return "Unable to connect to the weather service."
