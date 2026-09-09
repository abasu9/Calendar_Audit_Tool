"""Build Django database settings from environment variables.

The project accepts either one PostgreSQL URL, such as a Supabase connection
string, or separate local PostgreSQL values. Connection options are normalized
before Django opens the database.
"""

import os
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured


LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
SUPPORTED_POSTGRES_OPTIONS = {
    "application_name",
    "connect_timeout",
    "keepalives",
    "keepalives_count",
    "keepalives_idle",
    "keepalives_interval",
    "options",
    "sslcert",
    "sslkey",
    "sslmode",
    "sslrootcert",
    "target_session_attrs",
}


def _env_bool(environ, name, default=False):
    """Read one environment value as a boolean.

    Common true values are accepted without regard to letter case; missing or
    different values use the supplied default or evaluate to false.
    """
    value = environ.get(name, str(default))
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(environ, name, default):
    """Read one environment value as an integer.

    The value is converted with ``int`` and a Django configuration error is
    raised when it cannot be converted.
    """
    value = environ.get(name, str(default))
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc


def database_config_from_env(environ=None):
    """Return Django settings for the configured PostgreSQL database.

    A ``DATABASE_URL`` is parsed first; otherwise the separate ``POSTGRES_*``
    values are used. Remote connections default to SSL, and port 6543 enables
    options that are safe for Supabase transaction pooling.
    """
    environ = os.environ if environ is None else environ
    database_url = environ.get("DATABASE_URL", "").strip()

    if not database_url:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": environ.get("POSTGRES_DB", "calendar_audit"),
            "USER": environ.get("POSTGRES_USER", ""),
            "PASSWORD": environ.get("POSTGRES_PASSWORD", ""),
            "HOST": environ.get("POSTGRES_HOST", "localhost"),
            "PORT": environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": _env_int(environ, "DB_CONN_MAX_AGE", 0),
            "CONN_HEALTH_CHECKS": _env_bool(
                environ, "DB_CONN_HEALTH_CHECKS", True
            ),
        }

    try:
        parsed = urlsplit(database_url)
        port = parsed.port or 5432
    except ValueError as exc:
        raise ImproperlyConfigured("DATABASE_URL contains an invalid port.") from exc

    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured(
            "DATABASE_URL must start with postgres:// or postgresql://."
        )
    if not parsed.hostname or not parsed.path.lstrip("/"):
        raise ImproperlyConfigured(
            "DATABASE_URL must include a database host and database name."
        )

    query_options = dict(parse_qsl(parsed.query, keep_blank_values=False))
    options = {
        key: value
        for key, value in query_options.items()
        if key in SUPPORTED_POSTGRES_OPTIONS
    }

    # Use an explicit SSL choice, or protect remote connections by default.
    sslmode = environ.get("DB_SSLMODE")
    if sslmode:
        options["sslmode"] = sslmode
    elif "sslmode" not in options and parsed.hostname not in LOCAL_DATABASE_HOSTS:
        options["sslmode"] = "require"

    connect_timeout = environ.get("DB_CONNECT_TIMEOUT")
    if connect_timeout:
        options["connect_timeout"] = str(
            _env_int(environ, "DB_CONNECT_TIMEOUT", 10)
        )

    is_transaction_pooler = port == 6543
    if is_transaction_pooler:
        # Transaction poolers cannot keep prepared statements between requests.
        options["prepare_threshold"] = None

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": str(port),
        "CONN_MAX_AGE": _env_int(environ, "DB_CONN_MAX_AGE", 0),
        "CONN_HEALTH_CHECKS": _env_bool(
            environ, "DB_CONN_HEALTH_CHECKS", True
        ),
        "OPTIONS": options,
    }
    if is_transaction_pooler:
        config["DISABLE_SERVER_SIDE_CURSORS"] = True

    return config
