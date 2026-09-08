"""
Django Settings for Calendar Audit Tool

PURPOSE:
Central configuration for the entire Django application. This file defines:
- Database connection settings
- Installed apps and middleware
- Security settings (secret key, allowed hosts)
- Google OAuth configuration
- Timezone and localization settings

HOW SETTINGS WORK:
Django loads this file at startup. Other parts of the app access settings via:
    from django.conf import settings
    print(settings.DEBUG)

ENVIRONMENT VARIABLES:
Most sensitive settings come from environment variables (loaded from .env file).
This keeps secrets out of source code. The python-dotenv library loads .env automatically.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

# =============================================================================
# BASE DIRECTORY
# =============================================================================
# Path to the project root (the folder containing manage.py)
# __file__ = this settings.py file
# .parent = config/
# .parent = project root
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file in project root
# This makes os.getenv() return values from .env
load_dotenv(BASE_DIR / ".env")


# =============================================================================
# HELPER FUNCTIONS FOR PARSING ENVIRONMENT VARIABLES
# =============================================================================

def env_bool(name, default=False):
    """
    Parse a boolean from an environment variable.
    
    Treats these as True: "1", "true", "yes", "on" (case insensitive)
    Everything else is False.
    
    EXAMPLE:
        DEBUG=true  -> True
        DEBUG=0     -> False
        DEBUG=      -> False (uses default)
    """
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """
    Parse a comma-separated list from an environment variable.
    
    EXAMPLE:
        ALLOWED_HOSTS=localhost,127.0.0.1  -> ["localhost", "127.0.0.1"]
        ALLOWED_HOSTS=                      -> []
    """
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# =============================================================================
# SECURITY SETTINGS
# =============================================================================

# Secret key for cryptographic signing (sessions, CSRF tokens, etc.)
# IMPORTANT: Change this in production! Generate with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-dev-only-change-me")

# Debug mode: shows detailed error pages, disables some security features
# NEVER enable in production!
DEBUG = env_bool("DEBUG", True)

# Hostnames that Django will serve requests for
# Prevents HTTP Host header attacks
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# Origins that can make cross-site requests (needed for webhooks in Phase 2)
# Google sends push notifications to an HTTPS tunnel hostname
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")


# =============================================================================
# APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    # Django built-in apps
    "django.contrib.admin",          # Admin interface
    "django.contrib.auth",           # User authentication
    "django.contrib.contenttypes",   # Content type framework
    "django.contrib.sessions",       # Session handling (stores OAuth state)
    "django.contrib.messages",       # Flash messages
    "django.contrib.staticfiles",    # Static file serving
    
    # Third-party apps
    "rest_framework",                # Django REST Framework for APIs
    
    # Our apps
    "googlecal",  # Google OAuth and Calendar API integration (Phase 1)
    "calsync",    # Calendar sync engine with push notifications (Phase 2)
    "calaudit",   # Audit report generation and API (Phase 3)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",      # Security headers
    "django.contrib.sessions.middleware.SessionMiddleware",  # Session handling
    "django.middleware.common.CommonMiddleware",          # URL rewriting, etc.
    "django.middleware.csrf.CsrfViewMiddleware",          # CSRF protection
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # User auth
    "django.contrib.messages.middleware.MessageMiddleware",     # Flash messages
    "django.middleware.clickjacking.XFrameOptionsMiddleware",   # Clickjacking protection
]

ROOT_URLCONF = "config.urls"  # Main URL configuration module

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # Project-level templates
        "APP_DIRS": True,  # Also look in app_name/templates/
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"  # For traditional web servers
ASGI_APPLICATION = "config.asgi.application"  # For async servers


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

def postgres_config():
    """
    Build PostgreSQL connection settings from environment variables.
    
    SUPPORTS TWO FORMATS:
    1. DATABASE_URL (e.g., postgresql://user:pass@host:5432/dbname)
       - Common in cloud platforms like Heroku, Railway
    2. Discrete variables (POSTGRES_DB, POSTGRES_USER, etc.)
       - More explicit, easier to read in .env files
    
    DATABASE_URL takes priority if set.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        # Use discrete environment variables
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "calendar_audit"),
            "USER": os.getenv("POSTGRES_USER", ""),  # Empty = OS username
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }

    # Parse DATABASE_URL
    # Example: postgresql://myuser:mypassword@localhost:5432/mydb
    parsed = urlsplit(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),  # /mydb -> mydb
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or "5432"),
    }


DATABASES = {"default": postgres_config()}


# =============================================================================
# PASSWORD VALIDATION (for Django's auth system)
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Default primary key type for models
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # Store all times in UTC in the database
USE_I18N = True    # Enable translation system
USE_TZ = True      # Use timezone-aware datetimes

# Timezone for DISPLAY in reports and UI
# Calendar data is stored in UTC; this only affects presentation
REPORT_TIME_ZONE = os.getenv("REPORT_TIME_ZONE", "America/Chicago")


# =============================================================================
# STATIC FILES (CSS, JavaScript, Images)
# =============================================================================

STATIC_URL = "static/"


# =============================================================================
# GOOGLE CALENDAR INTEGRATION
# =============================================================================

def project_path(name, default):
    """
    Resolve a path from an environment variable, treating relative paths
    as relative to the project root.
    
    EXAMPLE:
        GOOGLE_CREDENTIALS_FILE=credentials.json -> /path/to/project/credentials.json
        GOOGLE_CREDENTIALS_FILE=/etc/creds.json  -> /etc/creds.json
    """
    return (BASE_DIR / os.getenv(name, default)).resolve()


# Path to the OAuth client JSON downloaded from Google Cloud Console
GOOGLE_CREDENTIALS_FILE = project_path("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Path where we store the user's access/refresh tokens after authorization
GOOGLE_TOKEN_FILE = project_path("GOOGLE_TOKEN_FILE", "token.json")

# OAuth scopes (permissions) we request from the user
# - openid: Get the user's Google ID
# - userinfo.email: Get the user's email address
# - calendar.readonly: Read calendar events (also allows setting up push notifications)
GOOGLE_OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# The callback URL Google redirects to after user authorizes
# MUST be registered in Google Cloud Console under "Authorized redirect URIs"
# MUST match exactly, including trailing slash
GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/oauth2/callback/"
)

# =============================================================================
# OAUTHLIB WORKAROUNDS
# =============================================================================

if DEBUG and GOOGLE_OAUTH_REDIRECT_URI.startswith("http://"):
    # By default, oauthlib requires HTTPS for OAuth callbacks (security best practice)
    # But Google allows http://localhost for development
    # This env var tells oauthlib to allow insecure transport in debug mode
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# Google returns scopes in a different order than we requested, and sometimes
# adds aliases (like "openid" -> "openid email profile"). oauthlib treats this
# as a scope-change attack and raises an error. This env var relaxes that check.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


# =============================================================================
# LOGGING
# =============================================================================

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
