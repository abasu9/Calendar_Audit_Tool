"""Load Google credentials and create Calendar API clients.

OAuth credentials are read from the configured token file and refreshed when
possible. The resulting credentials are passed to Google's Calendar v3 client so
the rest of the project does not repeat authentication logic.

The only supported authorisation path is the web OAuth flow at ``/oauth2/start/``.
There is no interactive CLI flow.
"""

import logging

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class GoogleAuthError(RuntimeError):
    """Report that usable Google credentials could not be obtained."""

    pass


def load_credentials():
    """Return valid saved credentials, refreshing if they have expired.

    The token file is loaded first. Expired credentials with a refresh token are
    renewed and saved. If no usable token exists, ``GoogleAuthError`` is raised
    so the caller can redirect the user to ``/oauth2/start/``.
    """
    token_file = settings.GOOGLE_TOKEN_FILE
    scopes = settings.GOOGLE_OAUTH_SCOPES

    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired Google credentials")
        creds.refresh(Request())
        save_credentials(creds)
        return creds

    raise GoogleAuthError(
        f"No usable Google credentials at {token_file}. Start the server and "
        "visit http://localhost:8000/ to authorise with Google."
    )


def save_credentials(creds):
    """Save OAuth credentials in the configured private token file.

    Parent folders are created when needed, Google's JSON form is written, and
    owner-only permissions protect access and refresh tokens on supported systems.
    """
    token_file = settings.GOOGLE_TOKEN_FILE
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    token_file.chmod(0o600)


def build_service(*, credentials=None):
    """Return an authenticated Google Calendar v3 service object.

    Supplied credentials are reused; otherwise they are loaded through
    ``load_credentials``. Discovery caching is disabled so the client does not
    create outdated cache files or related warnings.
    """
    creds = credentials or load_credentials()

    return build("calendar", "v3", credentials=creds, cache_discovery=False)
