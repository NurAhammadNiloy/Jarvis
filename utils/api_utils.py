import requests

# Base URL of the Flask API
BASE_URL = "http://10.114.0.49:5000"

def fetch_latest_temperature():
    """
    Fetch the latest room temperature from the Flask API.
    """
    try:
        response = requests.get(f"{BASE_URL}/latest-temperature", timeout=5)
        response.raise_for_status()
        data = response.json()
        if "temperature" in data:
            return data
        else:
            print("Unexpected response format for latest temperature.")
            return None
    except requests.RequestException as e:
        print(f"Error fetching latest temperature: {e}")
        return None


def fetch_latest_humidity():
    """
    Fetch the latest room humidity from the Flask API.
    """
    try:
        response = requests.get(f"{BASE_URL}/latest-humidity", timeout=5)
        response.raise_for_status()
        data = response.json()
        if "humidity" in data:
            return data
        else:
            print("Unexpected response format for latest humidity.")
            return None
    except requests.RequestException as e:
        print(f"Error fetching latest humidity: {e}")
        return None


def fetch_daily_averages():
    """
    Fetch the daily average temperature and humidity from the Flask API.
    """
    try:
        response = requests.get(f"{BASE_URL}/daily-averages", timeout=5)
        response.raise_for_status()
        data = response.json()
        if "average_temperature" in data and "average_humidity" in data:
            return data
        else:
            print("Unexpected response format for daily averages.")
            return None
    except requests.RequestException as e:
        print(f"Error fetching daily averages: {e}")
        return None


def fetch_weekly_averages():
    """
    Fetch the weekly average temperature and humidity from the Flask API.
    """
    try:
        response = requests.get(f"{BASE_URL}/weekly-averages", timeout=5)
        response.raise_for_status()
        data = response.json()
        if "average_temperature" in data and "average_humidity" in data:
            return data
        else:
            print("Unexpected response format for weekly averages.")
            return None
    except requests.RequestException as e:
        print(f"Error fetching weekly averages: {e}")
        return None

# Removed the fetch_hourly_average function
