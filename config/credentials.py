"""Google Cloud credentials, loaded on first use rather than at import."""
import os

_credentials = None


def get_credentials():
    """Return service-account credentials from GOOGLE_CLOUD_CREDENTIALS (cached)."""
    global _credentials
    if _credentials is None:
        from dotenv import load_dotenv
        from google.oauth2 import service_account
        load_dotenv()
        path = os.getenv("GOOGLE_CLOUD_CREDENTIALS")
        if not path:
            raise RuntimeError(
                "GOOGLE_CLOUD_CREDENTIALS is not set. Set it in .env to the path of "
                "your Google service-account JSON key (see .env.example).")
        if not os.path.isfile(path):
            raise RuntimeError(
                f"GOOGLE_CLOUD_CREDENTIALS points to a file that does not exist: {path}")
        _credentials = service_account.Credentials.from_service_account_file(path)
    return _credentials


def __getattr__(name):
    # Keeps `from config.credentials import credentials` working for the
    # standalone experiment scripts; the load happens on that first access.
    if name == "credentials":
        return get_credentials()
    raise AttributeError(name)
