"""
Google Calendar Credential Management and API Client Factory

PURPOSE:
This module handles two things:
1. Loading/saving/refreshing Google OAuth credentials (the tokens)
2. Building a Google Calendar API client ready to make requests

CREDENTIAL LIFECYCLE:
1. User authorizes via OAuth flow -> we get access_token + refresh_token
2. We save these to token.json (or database in Phase 2)
3. When we need to call the API:
   a. Load credentials from token.json
   b. If expired, use refresh_token to get a new access_token
   c. Build an API client with the valid credentials
   d. Make API calls

TOKEN FILE (token.json):
Contains a JSON object with:
- access_token: The actual bearer token sent with API requests (expires in ~1 hour)
- refresh_token: Used to get new access_tokens without user interaction
- token_uri: Google's token endpoint for refreshing
- client_id, client_secret: Needed for refresh requests
- scopes: What permissions were granted
- expiry: When the access_token expires
"""

import logging

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class GoogleAuthError(RuntimeError):
    """
    Custom exception for Google authentication problems.
    
    Raised when:
    - No token.json exists and interactive auth isn't allowed
    - Token is expired and has no refresh_token
    - Trying to use desktop flow with a web client
    """
    pass


def load_credentials(*, allow_interactive=False):
    """
    Load Google OAuth credentials, refreshing if expired.
    
    WHAT THIS DOES:
    1. Check if token.json exists
       - If yes: load the credentials from it
       - If no: either raise error or start interactive flow (depending on allow_interactive)
    2. If credentials exist but are expired:
       - If we have a refresh_token: automatically refresh and save
       - If no refresh_token: need to re-authorize
    3. Return valid credentials ready for API use
    
    PARAMETERS:
    - allow_interactive: If True and no valid token exists, start the desktop OAuth flow
                         (opens a browser). Only works with "installed" type clients.
                         Default False because web requests shouldn't open browsers.
    
    RETURNS:
    - google.oauth2.credentials.Credentials object with valid access_token
    
    RAISES:
    - GoogleAuthError if credentials can't be obtained
    
    WHY THE KEYWORD-ONLY SYNTAX (*)?
    The * before allow_interactive forces callers to write:
        load_credentials(allow_interactive=True)
    instead of:
        load_credentials(True)
    This prevents bugs from positional argument confusion.
    """
    token_file = settings.GOOGLE_TOKEN_FILE
    scopes = settings.GOOGLE_OAUTH_SCOPES

    creds = None
    
    # Step 1: Try to load existing credentials from token.json
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    # Step 2: If we have valid (non-expired) credentials, return them
    if creds and creds.valid:
        return creds

    # Step 3: If credentials exist but are expired, try to refresh
    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired Google credentials")
        # This makes an HTTP request to Google's token endpoint
        # using the refresh_token to get a new access_token
        creds.refresh(Request())
        # Save the new tokens (access_token changed, refresh_token usually stays same)
        save_credentials(creds)
        return creds

    # Step 4: No valid credentials - need to authorize
    if not allow_interactive:
        # We can't open a browser in a web request context
        raise GoogleAuthError(
            f"No usable Google credentials at {token_file}. Start the server and "
            "visit http://localhost:8000/ to authorise with Google."
        )

    # Step 5: Interactive mode - try desktop OAuth flow
    credentials_file = settings.GOOGLE_CREDENTIALS_FILE
    if not credentials_file.exists():
        raise GoogleAuthError(
            f"Missing OAuth client file at {credentials_file}. Download the OAuth "
            "2.0 Client ID JSON from the Google Cloud console and save it there."
        )

    # Import here to avoid circular imports (oauth.py imports from client.py)
    from googlecal.oauth import client_type

    # Desktop flow only works with "installed" type clients
    if client_type() == "web":
        # Web clients require a pre-registered redirect URI
        # The desktop flow uses http://localhost:<random-port>/ which can't be registered
        raise GoogleAuthError(
            "This OAuth client is a 'web' application, which cannot use the "
            "command-line loopback flow. Run `manage.py runserver` and authorise "
            "at http://localhost:8000/ instead."
        )

    # Step 6: Run the desktop OAuth flow (opens browser, starts local server)
    logger.info("Starting interactive OAuth flow")
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    # run_local_server(port=0) picks a random available port, starts a tiny HTTP server,
    # opens the browser to Google's consent page, waits for the redirect, and returns credentials
    creds = flow.run_local_server(port=0)
    save_credentials(creds)
    return creds


def save_credentials(creds):
    """
    Save credentials to the token file for future use.
    
    WHAT THIS DOES:
    1. Ensure the parent directory exists
    2. Write the credentials as JSON to token.json
    3. Set file permissions to 600 (owner read/write only) for security
    
    WHY SAVE?
    - access_token expires in ~1 hour, but we save it anyway
    - refresh_token is long-lived and lets us get new access_tokens
    - Without saving, user would need to re-authorize every time
    
    PARAMETERS:
    - creds: google.oauth2.credentials.Credentials object
    
    FILE FORMAT (token.json):
    {
        "token": "ya29.xxx...",           // access_token
        "refresh_token": "1//xxx...",     // for getting new access_tokens
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "xxx.apps.googleusercontent.com",
        "client_secret": "xxx",
        "scopes": ["openid", "..."],
        "expiry": "2024-01-01T12:00:00Z"
    }
    """
    token_file = settings.GOOGLE_TOKEN_FILE
    # Create parent directories if they don't exist
    token_file.parent.mkdir(parents=True, exist_ok=True)
    # Write credentials as JSON
    token_file.write_text(creds.to_json())
    # Set permissions: only owner can read/write (security best practice for tokens)
    token_file.chmod(0o600)


def build_service(*, allow_interactive=False, credentials=None):
    """
    Create a Google Calendar API client ready to make requests.
    
    WHAT THIS DOES:
    1. Get valid credentials (either passed in or loaded from token.json)
    2. Build a "service" object that provides methods for API calls
    
    WHAT IS A SERVICE?
    The googleapiclient library uses "discovery" to auto-generate API methods.
    For Calendar v3, you get methods like:
    - service.events().list(calendarId="primary", ...).execute()
    - service.events().get(calendarId="primary", eventId="xxx").execute()
    - service.calendars().get(calendarId="primary").execute()
    
    PARAMETERS:
    - allow_interactive: Passed to load_credentials() if we need to load them
    - credentials: Optional pre-loaded credentials. If provided, we skip loading.
    
    RETURNS:
    - A googleapiclient Resource object for the Calendar v3 API
    
    WHY cache_discovery=False?
    The library can cache the API schema to disk, but the default caching
    uses oauth2client which prints deprecation warnings. Disabling it is cleaner.
    """
    # Get credentials - either use provided ones or load from file
    creds = credentials or load_credentials(allow_interactive=allow_interactive)
    
    # Build the API client
    # "calendar" = the API name, "v3" = the version
    # This downloads the API schema from Google and generates Python methods
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
