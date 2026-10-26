import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent

ENVIRONMENT = os.environ["ENVIRONMENT"]
DATABASE_URL = os.environ["DATABASE_URL"]

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ["JWT_ALGORITHM"]
JWT_EXPIRE_MINUTES = int(os.environ["JWT_EXPIRE_MINUTES"])
OTP_EXPIRE_MINUTES = max(1, min(int(os.environ["OTP_EXPIRE_MINUTES"]), 5))
OTP_MAX_ATTEMPTS = int(os.environ["OTP_MAX_ATTEMPTS"])

FRONTEND_URL = os.environ["FRONTEND_URL"].rstrip("/")

CORS_ORIGINS = [
    origin.strip() for origin in os.environ["CORS_ORIGINS"].split(",") if origin.strip()
]

ORS_API_KEY = os.environ["ORS_API_KEY"]
ORS_BASE_URL = os.environ["ORS_BASE_URL"]
ORS_GEOCODE_URL = os.environ["ORS_GEOCODE_URL"]

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ["GEMINI_MODEL"]

GEMINI_FALLBACK_MODELS = [
    model.strip()
    for model in os.environ["GEMINI_FALLBACK_MODELS"].split(",")
    if model.strip()
]

GEMINI_TIMEOUT_SECONDS = int(os.environ["GEMINI_TIMEOUT_SECONDS"])
GEMINI_FILE_SEARCH_STORE = os.environ["GEMINI_FILE_SEARCH_STORE"].strip()

GEMINI_REFERENCE_DIR = PROJECT_ROOT / os.environ["GEMINI_REFERENCE_DIR"]
GEMINI_FILE_STATE_PATH = PROJECT_ROOT / os.environ["GEMINI_FILE_STATE_PATH"]
GEMINI_FILE_SEARCH_STATE_PATH = (
    PROJECT_ROOT / os.environ["GEMINI_FILE_SEARCH_STATE_PATH"]
)

EMAIL_HOST = os.environ["EMAIL_HOST"]
EMAIL_PORT = int(os.environ["EMAIL_PORT"])
EMAIL_USERNAME = os.environ["EMAIL_USERNAME"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_FROM = os.environ["EMAIL_FROM"]
EMAIL_USE_TLS = os.environ["EMAIL_USE_TLS"].lower() == "true"

UPLOAD_DIR = Path(os.environ["UPLOAD_DIR"])

UNACCEPTED_CARGO_TYPES = {
    item.strip().lower()
    for item in os.environ["UNACCEPTED_CARGO_TYPES"].split(",")
    if item.strip()
}

REDIS_URL = os.environ["REDIS_URL"]
