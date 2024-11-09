from google.oauth2 import service_account

GOOGLE_CREDENTIALS_FILE = "F:/Projects/JERVIS/jervis-439422-1ee6e5e6265f.json"
credentials = service_account.Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE)

