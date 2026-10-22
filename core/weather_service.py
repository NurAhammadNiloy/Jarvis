import requests
import geocoder
from datetime import datetime
from config.api_keys import WEATHER_API_KEY, GOOGLE_API_KEY
from config.settings import NETWORK_TIMEOUT_SECONDS
from core.phrases import part, say
from core.service_errors import ServiceError

def get_user_location():
    try:
        g = geocoder.ip('me', timeout=NETWORK_TIMEOUT_SECONDS)
        if g.ok and g.city:
            return g.city
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def get_precise_location():
    url = f'https://www.googleapis.com/geolocation/v1/geolocate?key={GOOGLE_API_KEY}'
    try:
        response = requests.post(url, json={}, timeout=NETWORK_TIMEOUT_SECONDS)
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
        response = requests.get(url, headers=headers, timeout=NETWORK_TIMEOUT_SECONDS)
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
    """'10 degrees', '1 degree', '0 degrees'."""
    if -0.5 < temperature < 0.5:
        return part("temp_zero")
    rounded = round(temperature)
    return part("temp_one" if abs(rounded) == 1 else "temp_many", n=rounded)

def _get_feels_like_description(actual, feels_like):
    """Describe the 'feels like' temperature difference."""
    diff = feels_like - actual
    if diff < -5:
        key = "feels_much_colder"
    elif diff < -2:
        key = "feels_colder"
    elif diff > 5:
        key = "feels_much_warmer"
    elif diff > 2:
        key = "feels_warmer"
    else:
        return ""
    return part(key, temp=_format_temperature(feels_like))

def _get_wind_description(wind_speed):
    """Get a human-friendly wind description."""
    if wind_speed < 1:
        return part("wind_calm")
    elif wind_speed < 4:
        return part("wind_light")
    elif wind_speed < 8:
        return part("wind_moderate")
    elif wind_speed < 14:
        return part("wind_quite")
    elif wind_speed < 20:
        return part("wind_very")
    else:
        return part("wind_extreme")

def _get_humidity_comment(humidity, temperature):
    """Get humidity-related comfort comment."""
    if humidity > 80 and temperature > 20:
        return say("weather_humid_high")
    elif humidity < 30:
        return say("weather_dry")
    return ""

def _get_time_of_day():
    """Get current time of day for contextual responses."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return part("part_morning")
    elif 12 <= hour < 17:
        return part("part_afternoon")
    elif 17 <= hour < 21:
        return part("part_evening")
    else:
        return part("part_night")

def _get_activity_suggestion(weather, temperature, wind_speed, is_daytime):
    """Suggest activities based on current conditions."""
    if temperature <= -15:
        return say("activity_indoors_book")
    elif temperature <= -5:
        if "clear" in weather or "snow" in weather:
            return say("activity_winter_walk")
        return say("activity_cozy")
    elif temperature <= 5:
        if "rain" in weather:
            return say("activity_indoor")
        return say("activity_brisk")
    elif 15 <= temperature <= 25:
        if "clear" in weather and is_daytime:
            return say("activity_outdoor")
        elif "cloud" in weather:
            return say("activity_walk")
        elif "rain" in weather:
            return say("activity_save_plans")
    elif temperature > 25:
        if is_daytime:
            return say("activity_hydrated")
        return say("activity_evening")
    return ""

def _get_clothing_suggestion(temperature, weather, wind_speed):
    """Suggest appropriate clothing."""
    keys = []

    if temperature <= -20:
        keys = ["wear_thermal", "wear_heavy_coat", "wear_boots_insulated", "wear_gloves", "wear_hat_warm", "wear_scarf"]
    elif temperature <= -10:
        keys = ["wear_layers", "wear_winter_coat", "wear_boots_warm", "wear_gloves", "wear_hat"]
    elif temperature <= 0:
        keys = ["wear_winter_jacket", "wear_warm_layers", "wear_gloves"]
    elif temperature <= 10:
        keys = ["wear_warm_jacket"]
    elif temperature <= 18:
        keys = ["wear_light_jacket"]
    elif temperature > 28:
        keys = ["wear_breathable"]

    if "rain" in weather and temperature > 0:
        keys.append("wear_umbrella")
    if "snow" in weather:
        keys.append("wear_boots_waterproof")
    if wind_speed > 10 and temperature < 10:
        keys.append("wear_windbreaker")

    suggestions = [part(key) for key in keys]
    if not suggestions:
        return ""
    elif len(suggestions) == 1:
        return say("weather_recommend_one", items=suggestions[0])
    else:
        return say("weather_recommend_many", items=', '.join(suggestions[:-1]), last=suggestions[-1])

# Questions answered with one short sentence (the key reason) unless details are asked for.
ADVICE_CONTEXTS = ("clothing", "go_outside", "umbrella")

def _get_advice(context, temperature, feels_like, weather, wind_speed):
    """'Light jacket: 10 degrees and breezy.' / 'No: clear sky.' / 'Yes: 10 degrees, clear sky.'"""
    temp = _format_temperature(temperature)
    wet = any(word in weather for word in ("rain", "drizzle", "shower", "thunder"))
    snow = "snow" in weather
    if context == "umbrella":
        return say("adv_umbrella_yes" if wet else "adv_umbrella_snow" if snow else "adv_umbrella_no", weather=weather)
    if context == "go_outside":
        if temperature <= -15:
            return say("adv_go_stay", temp=temp)
        if temperature <= 5:
            return say("adv_go_bundle", temp=temp, weather=weather)
        if wet or "storm" in weather:
            return say("adv_go_wait", weather=weather)
        return say("adv_go_yes", temp=temp, weather=weather)
    if temperature <= -20:
        item = "adv_item_thermal"
    elif temperature <= -10:
        item = "adv_item_heavy"
    elif temperature <= 0:
        item = "adv_item_winter"
    elif temperature < 10:
        item = "adv_item_warm"
    elif temperature <= 18:
        item = "adv_item_light"
    else:
        item = "adv_item_none"
    # The one thing that matters most: rain or snow, then a wind chill, then wind.
    if wet:
        extra = part("adv_and_rainy")
    elif snow:
        extra = part("adv_and_snowy")
    elif feels_like - temperature <= -4:
        extra = part("adv_feels", temp=_format_temperature(feels_like))
    elif wind_speed >= 8:
        extra = part("adv_and_windy")
    elif wind_speed >= 4:
        extra = part("adv_and_breezy")
    else:
        extra = ""
    return say("adv_wear", item=part(item), reason=temp + extra)

def get_weather(city, detailed=False, question_context=None):
    """Get comprehensive weather information for a city.

    Args:
        city: City name
        detailed: Whether to include full details
        question_context: Type of question asked ('go_outside', 'clothing', 'umbrella', 'temperature').
            Advice questions get one short sentence unless details were asked for.
    """
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": WEATHER_API_KEY,
        "units": "metric"
    }

    try:
        response = requests.get(base_url, params=params, timeout=NETWORK_TIMEOUT_SECONDS)
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

            # ADVICE - "should I wear a jacket?": one sentence with the key reason
            if not detailed and question_context in ADVICE_CONTEXTS:
                return _get_advice(question_context, temperature, feels_like, weather, wind_speed)

            # BRIEF MODE - concise response
            if not detailed:
                values = dict(city=city, temp=temp_text, feels=feels_like_text, weather=weather)
                if temperature <= -15:
                    return say("weather_brief_extreme", **values)
                elif temperature <= -5:
                    return say("weather_brief_very_cold", **values)
                elif temperature <= 0:
                    return say("weather_brief_freezing", **values)
                elif temperature <= 10:
                    return say("weather_brief_cool", **values)
                elif temperature <= 20:
                    return say("weather_brief_mild", **values)
                elif temperature <= 28:
                    return say("weather_brief_pleasant", **values)
                else:
                    return say("weather_brief_hot", **values)

            # DETAILED MODE - full response with suggestions
            parts = []
            values = dict(city=city, temp=temp_text, feels=feels_like_text, weather=weather, part=time_of_day)

            # Contextual opener based on question type
            if question_context == "go_outside":
                # "Should I go outside?" - Direct answer first
                if temperature <= -15:
                    parts.append(say("weather_go_no"))
                elif temperature <= -5:
                    parts.append(say("weather_go_bundle"))
                elif temperature <= 5:
                    parts.append(say("weather_go_dress"))
                elif 15 <= temperature <= 25 and "rain" not in weather:
                    parts.append(say("weather_go_lovely"))
                elif "rain" in weather or "storm" in weather:
                    parts.append(say("weather_go_wait"))
                else:
                    parts.append(say("weather_go_decent"))
            elif question_context == "clothing":
                # "What should I wear?" - Lead with clothing
                parts.append(say("weather_wear_opener", city=city))
                if clothing:
                    parts.append(clothing)
            elif question_context == "temperature":
                # "How cold/hot is it?" - Temperature focused
                parts.append(say("weather_temp_opener", **values))

            # Weather details (skip the intro if we already have a contextual opener)
            if question_context:
                # Add condensed weather info after contextual opener
                parts.append(say("weather_context", **values))
            elif temperature <= -20:
                parts.append(say("weather_d_dangerous", **values))
                parts.append(say("weather_d_conditions", **values))
                parts.append(say("weather_d_indoors"))
            elif temperature <= -10:
                parts.append(say("weather_d_very_cold", **values))
            elif temperature <= 0:
                parts.append(say("weather_d_freezing", **values))
            elif temperature <= 10:
                parts.append(say("weather_d_cool", **values))
            elif temperature <= 20:
                if "clear" in weather or "sun" in weather:
                    parts.append(say("weather_d_lovely", **values))
                else:
                    parts.append(say("weather_d_mild", **values))
            elif temperature <= 28:
                parts.append(say("weather_d_warm", **values))
            else:
                parts.append(say("weather_d_hot", **values))

            # Wind information (if notable)
            if wind_speed >= 4:
                parts.append(say("weather_wind", wind=_get_wind_description(wind_speed), speed=round(wind_speed)))

            # Visibility warning
            if visibility < 1:
                parts.append(say("weather_vis_poor"))
            elif visibility < 5:
                parts.append(say("weather_vis_reduced"))

            # Humidity comment
            humidity_comment = _get_humidity_comment(humidity, temperature)
            if humidity_comment:
                parts.append(humidity_comment)

            # Clothing suggestion (skip if already added for clothing context)
            if question_context != "clothing" and clothing:
                parts.append(clothing)

            # Activity suggestion
            activity = _get_activity_suggestion(weather, temperature, wind_speed, is_daytime)
            if activity:
                parts.append(activity)

            # Detailed mode - add extra info
            if detailed:
                parts.append(say("weather_humidity_cloud", humidity=humidity, clouds=clouds))

            return " ".join(parts)

        elif response.status_code == 404:
            raise ServiceError(say("weather_not_found", city=city))
        elif response.status_code == 401:
            raise ServiceError(say("weather_auth"))
        else:
            raise ServiceError(say("weather_http", status=response.status_code))
    except requests.exceptions.Timeout:
        raise ServiceError(say("weather_timeout"))
    except requests.exceptions.RequestException:
        raise ServiceError(say("weather_connect"))

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
        response = requests.get(base_url, params=params, timeout=NETWORK_TIMEOUT_SECONDS)
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
                raise ServiceError(say("forecast_none", city=city))

            parts = [say("forecast_intro", city=city)]

            for i, (day, info) in enumerate(days_list):
                min_temp = round(min(info["temps"]))
                max_temp = round(max(info["temps"]))
                weather = max(set(info["weather"]), key=info["weather"].count)
                avg_wind = sum(info["wind"]) / len(info["wind"])

                # Make it conversational based on conditions
                if i == 0:
                    day_word = part("forecast_today") if datetime.now().strftime("%A") == day else day
                else:
                    day_word = day

                # Temperature description
                if max_temp <= -15:
                    temp_feel = part("forecast_dangerous")
                elif max_temp <= -5:
                    temp_feel = part("forecast_very_cold")
                elif max_temp <= 5:
                    temp_feel = part("forecast_chilly")
                elif max_temp <= 15:
                    temp_feel = part("forecast_cool")
                elif max_temp <= 25:
                    temp_feel = part("forecast_pleasant")
                else:
                    temp_feel = part("forecast_warm")

                # Weather advice
                if "snow" in weather:
                    weather_note = part("forecast_snow")
                elif "rain" in weather:
                    weather_note = part("forecast_rain")
                elif "clear" in weather:
                    weather_note = part("forecast_clear")
                elif "cloud" in weather:
                    weather_note = part("forecast_cloud")
                else:
                    weather_note = weather

                # Build the day's forecast naturally
                if min_temp == max_temp:
                    temp_text = part("forecast_around", n=min_temp)
                else:
                    temp_text = part("forecast_between", low=min_temp, high=max_temp)

                parts.append(say("forecast_day", day=day_word, feel=temp_feel, temp=temp_text, note=weather_note))

            # Add overall advice
            coldest = min(min(info["temps"]) for _, info in days_list)
            if coldest <= -10:
                parts.append(say("forecast_bundle"))
            elif any("rain" in max(set(info["weather"]), key=info["weather"].count) for _, info in days_list):
                parts.append(say("forecast_umbrella"))
            elif any("snow" in max(set(info["weather"]), key=info["weather"].count) for _, info in days_list):
                parts.append(say("forecast_winter"))

            return " ".join(parts)
        else:
            raise ServiceError(say("forecast_failed", city=city))
    except requests.exceptions.Timeout:
        raise ServiceError(say("weather_timeout"))
    except requests.exceptions.RequestException:
        raise ServiceError(say("forecast_connect"))

def compare_weather(city1, city2):
    """Compare weather between two cities."""
    # Get raw data for comparison
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    try:
        data1 = requests.get(base_url, params={"q": city1, "appid": WEATHER_API_KEY, "units": "metric"}, timeout=NETWORK_TIMEOUT_SECONDS).json()
        data2 = requests.get(base_url, params={"q": city2, "appid": WEATHER_API_KEY, "units": "metric"}, timeout=NETWORK_TIMEOUT_SECONDS).json()

        temp1 = data1["main"]["temp"]
        temp2 = data2["main"]["temp"]
        diff = abs(temp1 - temp2)

        if temp1 > temp2:
            comparison = say("compare_warmer", warm=city1, diff=_format_temperature(diff), cool=city2)
        elif temp2 > temp1:
            comparison = say("compare_warmer", warm=city2, diff=_format_temperature(diff), cool=city1)
        else:
            comparison = say("compare_same")

        return say("compare_line", city1=city1, temp1=_format_temperature(temp1), weather1=data1['weather'][0]['description'],
                   city2=city2, temp2=_format_temperature(temp2), weather2=data2['weather'][0]['description'],
                   comparison=comparison)
    except Exception:
        return say("compare_failed", city1=city1, city2=city2)
