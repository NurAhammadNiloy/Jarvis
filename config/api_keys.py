import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
