"""Configure Django, PostgreSQL, and Google Calendar integration.

Django loads these values when the application starts. Local environment values
come from ``.env`` so secrets and deployment-specific settings stay out of the
source code.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from config.database import database_config_from_env

# Project root containing ``manage.py``.
BASE_DIR = Path(__file__).resolve().parent.parent

# Add local ``.env`` values to the process environment.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    """Read one environment value as a boolean.

    Values such as ``1``, ``true``, ``yes``, and ``on`` become true after the
    text is normalized; all other values become false.
    """
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """Read a comma-separated environment value as a clean list.

    Each item is trimmed and empty items are removed before the list is returned.
    """
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# Django uses this value to sign sessions and security tokens.
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-dev-only-change-me")

# Detailed error pages are intended only for development.
DEBUG = env_bool("DEBUG", True)

# Only accept requests addressed to a known hostname.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# In development, accept changing ngrok subdomains used by the webhook tunnel.
if DEBUG:
    for _ngrok_host in (".ngrok-free.dev", ".ngrok-free.app", ".ngrok.io"):
        if _ngrok_host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_ngrok_host)

# Allow configured HTTPS tunnel origins to submit trusted requests.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")


INSTALLED_APPS = [
    # Django framework features.
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # REST API support.
    "rest_framework",
    # Project applications.
    "googlecal",
    "calsync",
    "calaudit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Build the default connection from ``DATABASE_URL`` or ``POSTGRES_*`` values.
DATABASES = {"default": database_config_from_env()}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Store timestamps in UTC, then display reports in this timezone.
REPORT_TIME_ZONE = os.getenv("REPORT_TIME_ZONE", "America/Chicago")


STATIC_URL = "static/"


def project_path(name, default):
    """Return an absolute path for a file setting.

    The environment value is used when present, and relative values are resolved
    from the project root so commands work from any current directory.
    """
    return (BASE_DIR / os.getenv(name, default)).resolve()


# OAuth client configuration downloaded from Google Cloud.
GOOGLE_CREDENTIALS_FILE = project_path("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Request identity details plus read-only calendar access.
GOOGLE_OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# This must exactly match an authorized redirect URI in Google Cloud.
GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/oauth2/callback/"
)

if DEBUG and GOOGLE_OAUTH_REDIRECT_URI.startswith("http://"):
    # Google permits an HTTP callback only for local development.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# Accept Google's equivalent identity-scope names and ordering.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


# Redirect anonymous users to the Google sign-in flow.
LOGIN_URL = "/oauth2/start/"

# Public HTTPS base URL used to build the Google Calendar webhook callback.
# In production set this to your domain, e.g. https://app.example.com
# For local development leave it unset and use `manage.py dev_watch` instead.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# How many days a Google push-notification channel should last before renewal.
WATCH_EXPIRATION_DAYS = int(os.getenv("WATCH_EXPIRATION_DAYS", "7"))


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
