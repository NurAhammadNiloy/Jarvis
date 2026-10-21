from google.oauth2 import service_account
from config.settings import DEFAULT_LOCATION

GOOGLE_CREDENTIALS_FILE = "F:/Projects/JERVIS/jervis-439422-1ee6e5e6265f.json"
credentials = service_account.Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE)

# Default location for weather (set to your city)
# This is used when GPS/IP detection is inaccurate
