"""
Django settings for the NEON RUSH game backend.

Configuration is driven by environment variables (see .env.example). Sensible
defaults let it run locally out of the box in MOCK_EXTERNAL mode with SQLite.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(key, default=False):
    return os.environ.get(key, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(key, default=""):
    raw = os.environ.get(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# --- core ---
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*") or ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "game",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "neonslot_api.urls"
WSGI_APPLICATION = "neonslot_api.wsgi.application"
TEMPLATES = []

# --- database (SQLite by default, Postgres if DATABASE_URL-style vars are set) ---
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- static (for gunicorn/whitenoise-free API; only the admin-less API is served) ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- CORS (the game frontend calls this API from another origin) ---
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL", True)
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_HEADERS = ["content-type", "authorization", "x-session-token"]

# ============================================================================
# Game configuration
# ============================================================================

# MOCK_EXTERNAL: when true, balances are stored locally in SQLite (MockBalance)
# so you can develop without the real balance backend. Turn OFF in production.
MOCK_EXTERNAL = env_bool("MOCK_EXTERNAL", True)

# The external balance backend (Liberty hustleback — owns real balances).
EXTERNAL_BASE_URL = os.environ.get("EXTERNAL_BASE_URL", "https://hustleback.libertydraw.com")
EXTERNAL_API_KEY = os.environ.get("EXTERNAL_API_KEY", "")
EXTERNAL_API_KEY_HEADER = os.environ.get("EXTERNAL_API_KEY_HEADER", "x-api-key")
EXTERNAL_TIMEOUT = float(os.environ.get("EXTERNAL_TIMEOUT", "10"))
# Separate debit (charge wallet/token) and credit (credit earning) endpoints.
EXTERNAL_CHARGE_PATH = os.environ.get("EXTERNAL_CHARGE_PATH", "/payment/other-games/charge/token/")
EXTERNAL_CREDIT_PATH = os.environ.get("EXTERNAL_CREDIT_PATH", "/payment/other-games/credit/earning/")
# Optional balance-read endpoint (none provided yet). If blank, no pre-check is
# done and the charge endpoint is the source of truth for affordability.
EXTERNAL_BALANCE_PATH = os.environ.get("EXTERNAL_BALANCE_PATH", "")
EXTERNAL_BALANCE_FIELD = os.environ.get("EXTERNAL_BALANCE_FIELD", "balance")

# Bets debit the TOKENS balance; wins are credited to the NAIRA wallet.
# Conversion: 1 naira = TOKENS_PER_NAIRA tokens, so a pot of N tokens pays N/rate naira.
TOKENS_PER_NAIRA = float(os.environ.get("TOKENS_PER_NAIRA", "4"))

# Optional shared secret: require this token (X-Session-Token header) on play
# endpoints. Leave blank to disable (NOT recommended for production).
SESSION_SHARED_SECRET = os.environ.get("SESSION_SHARED_SECRET", "")
