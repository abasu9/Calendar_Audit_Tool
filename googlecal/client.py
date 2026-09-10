"""Load per-user Google credentials and create Calendar API clients.

Each Django user has one ``GoogleCredential`` row. ``load_credentials`` reads
that row and builds a ``google.oauth2.credentials.Credentials`` object, refreshing
it when the access token has expired. ``save_credentials`` writes the result back.
``build_service`` wraps both steps and returns a ready-to-use Calendar v3 client.

The OAuth client ID and secret come from ``credentials.json`` at runtime via
``googlecal.oauth.client_config``; they are never duplicated across database rows.
"""

import logging
from datetime import timezone as tz

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class GoogleAuthError(RuntimeError):
    """Report that usable Google credentials could not be obtained."""

    pass


def load_credentials(user):
    """Return valid credentials for *user*, refreshing if they have expired.

    Reads the user's ``GoogleCredential`` row, reconstructs a
    ``google.oauth2.credentials.Credentials`` object, and refreshes it when the
    access token has expired. The refreshed value is persisted before returning.
    Raises ``GoogleAuthError`` when the user has no stored credentials.
    """
    from googlecal.models import GoogleCredential
    from googlecal.oauth import client_config

    try:
        row = GoogleCredential.objects.get(user=user)
    except GoogleCredential.DoesNotExist:
        raise GoogleAuthError(
            f"No Google credentials for user {user}. "
            "Visit / to connect your Google Calendar."
        )

    cfg = client_config()

    creds = Credentials(
        token=row.token,
        refresh_token=row.refresh_token or None,
        token_uri=row.token_uri,
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        scopes=row.scopes,
        expiry=row.expiry.replace(tzinfo=None) if row.expiry else None,
    )

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        logger.info("Refreshing expired Google credentials for user %s", user)
        creds.refresh(Request())
        save_credentials(user, creds)
        return creds

    raise GoogleAuthError(
        f"Google credentials for user {user} are invalid and could not be refreshed. "
        "Visit / to reconnect your Google Calendar."
    )


def save_credentials(user, creds, *, identity=None):
    """Persist OAuth credentials for *user* in the database.

    Called after the initial OAuth exchange and after each token refresh.
    Google omits ``refresh_token`` in refresh responses, so the existing value
    is kept when the incoming token is absent. ``identity`` (a dict with ``sub``
    and ``email``) is used on the first save to populate ``google_sub`` and
    ``email``; on subsequent saves those fields are left unchanged.
    """
    from googlecal.models import GoogleCredential

    expiry = None
    if creds.expiry:
        expiry = creds.expiry.replace(tzinfo=tz.utc)

    defaults = {
        "token": creds.token or "",
        "token_uri": creds.token_uri or "https://oauth2.googleapis.com/token",
        "scopes": list(creds.scopes or settings.GOOGLE_OAUTH_SCOPES),
        "expiry": expiry,
    }

    # Keep the stored refresh token when Google did not return a new one.
    if creds.refresh_token:
        defaults["refresh_token"] = creds.refresh_token

    if identity:
        defaults["google_sub"] = identity["sub"]
        defaults["email"] = identity.get("email", "")

    GoogleCredential.objects.update_or_create(user=user, defaults=defaults)
    logger.debug("Saved Google credentials for user %s", user)


def build_service(*, user=None, credentials=None):
    """Return an authenticated Google Calendar v3 service object.

    Supplied credentials are reused directly. When absent, ``load_credentials``
    is called with *user*. Exactly one of ``user`` or ``credentials`` must be
    provided. Discovery caching is disabled so the client does not write stale
    cache files.
    """
    if credentials is None:
        if user is None:
            raise ValueError("Either user or credentials must be provided.")
        credentials = load_credentials(user)

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)
