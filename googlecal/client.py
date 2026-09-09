"""Load Google credentials and create Calendar API clients.

OAuth credentials are read from the configured token file and refreshed when
possible. The resulting credentials are passed to Google's Calendar v3 client so
the rest of the project does not repeat authentication logic.
"""

import logging

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class GoogleAuthError(RuntimeError):
    """Report that usable Google credentials could not be obtained."""

    pass


def load_credentials(*, allow_interactive=False):
    """Return valid saved credentials, refreshing or authorizing when allowed.

    The token file is loaded first. Expired credentials with a refresh token are
    renewed and saved. If no usable token remains, web callers receive
    ``GoogleAuthError`` while explicitly interactive desktop callers may open the
    local browser flow.
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

    if not allow_interactive:
        raise GoogleAuthError(
            f"No usable Google credentials at {token_file}. Start the server and "
            "visit http://localhost:8000/ to authorise with Google."
        )

    credentials_file = settings.GOOGLE_CREDENTIALS_FILE
    if not credentials_file.exists():
        raise GoogleAuthError(
            f"Missing OAuth client file at {credentials_file}. Download the OAuth "
            "2.0 Client ID JSON from the Google Cloud console and save it there."
        )

    # Delay this import because the OAuth module also uses this client module.
    from googlecal.oauth import client_type

    if client_type() == "web":
        raise GoogleAuthError(
            "This OAuth client is a 'web' application, which cannot use the "
            "command-line loopback flow. Run `manage.py runserver` and authorise "
            "at http://localhost:8000/ instead."
        )

    logger.info("Starting interactive OAuth flow")
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    # A random free port receives Google's browser redirect for desktop clients.
    creds = flow.run_local_server(port=0)
    save_credentials(creds)
    return creds


def save_credentials(creds):
    """Save OAuth credentials in the configured private token file.

    Parent folders are created when needed, Google's JSON form is written, and
    owner-only permissions protect access and refresh tokens on supported systems.
    """
    token_file = settings.GOOGLE_TOKEN_FILE
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    token_file.chmod(0o600)


def build_service(*, allow_interactive=False, credentials=None):
    """Return an authenticated Google Calendar v3 service object.

    Supplied credentials are reused; otherwise they are loaded through
    ``load_credentials``. Discovery caching is disabled so the client does not
    create outdated cache files or related warnings.
    """
    creds = credentials or load_credentials(allow_interactive=allow_interactive)

    return build("calendar", "v3", credentials=creds, cache_discovery=False)
