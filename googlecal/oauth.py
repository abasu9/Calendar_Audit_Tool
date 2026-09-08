"""
Google OAuth 2.0 Authorization Code Flow (Server-Side / Web Application)

PURPOSE:
This module handles the OAuth 2.0 "authorization code" flow for web applications.
When a user wants to connect their Google Calendar, this module:
1. Generates the Google consent URL and redirects the user there
2. Handles the callback when Google redirects back with an authorization code
3. Exchanges that code for access/refresh tokens

WHY WEB FLOW (not desktop)?
The credentials.json you downloaded has type "web" (not "installed/desktop").
- Desktop apps use a "loopback" flow that redirects to http://localhost:<random-port>/
- Web apps MUST use a fixed redirect URI registered in Google Cloud Console
- Google rejects any redirect URI not pre-registered, hence the redirect_uri_mismatch error

PKCE (Proof Key for Code Exchange):
This flow uses PKCE for extra security:
1. We generate a random "code_verifier" and hash it to create "code_challenge"
2. We send code_challenge to Google in the authorization URL
3. Google returns an authorization code
4. We send the original code_verifier when exchanging the code for tokens
5. Google verifies the hash matches - this proves we're the same party who started the flow
"""

import json
import logging

from django.conf import settings
from google_auth_oauthlib.flow import Flow

logger = logging.getLogger(__name__)

# Session keys where we temporarily store OAuth state between requests
SESSION_STATE_KEY = "google_oauth_state"          # Random string to prevent CSRF
SESSION_VERIFIER_KEY = "google_oauth_code_verifier"  # PKCE verifier (must persist across requests)


class OAuthConfigError(RuntimeError):
    """
    Custom exception for OAuth configuration problems.
    
    Raised when:
    - credentials.json is missing or malformed
    - The OAuth state doesn't match (possible CSRF attack or expired session)
    - PKCE code_verifier is missing (session expired between start and callback)
    """
    pass


def client_type():
    """
    Determine whether credentials.json is for a "web" or "desktop" (installed) app.
    
    HOW IT WORKS:
    - Opens and parses credentials.json
    - Google's OAuth client JSON has a top-level key: either "web" or "installed"
    - "web" = Web application (requires registered redirect URIs)
    - "installed" = Desktop app (can use localhost with any port)
    
    RETURNS:
    - "web" or "installed" (string)
    
    RAISES:
    - OAuthConfigError if file is missing, invalid JSON, or wrong format
    """
    path = settings.GOOGLE_CREDENTIALS_FILE
    if not path.exists():
        raise OAuthConfigError(
            f"Missing OAuth client file at {path}. Download it from the Google "
            "Cloud console (APIs & Services > Credentials)."
        )

    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise OAuthConfigError(f"{path} is not valid JSON: {exc}") from exc

    for key in ("web", "installed"):
        if key in config:
            return key

    raise OAuthConfigError(
        f"{path} has no 'web' or 'installed' section, so it does not look like "
        "an OAuth client file. Make sure you downloaded the OAuth 2.0 Client ID "
        "JSON and not a service-account key."
    )


def build_flow(state=None):
    """
    Create a google_auth_oauthlib Flow object configured for our app.
    
    WHAT IS A FLOW?
    A Flow object manages the OAuth dance:
    - Knows your client_id, client_secret (from credentials.json)
    - Knows what permissions (scopes) to request
    - Knows where Google should redirect after consent (redirect_uri)
    - Can generate the authorization URL
    - Can exchange authorization codes for tokens
    
    PARAMETERS:
    - state: Optional random string for CSRF protection. If provided, this is
             a callback rebuilding the flow; if None, we're starting fresh.
    
    RETURNS:
    - A configured Flow object ready to generate URLs or exchange codes
    """
    client_type()  # Validate credentials.json exists and is valid before proceeding
    return Flow.from_client_secrets_file(
        str(settings.GOOGLE_CREDENTIALS_FILE),
        scopes=settings.GOOGLE_OAUTH_SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,  # Must match Google Console exactly!
        state=state,
    )


def authorization_url(request):
    """
    Generate the Google consent URL and prepare for the callback.
    
    THIS IS STEP 1 OF THE OAUTH FLOW:
    1. Create a Flow object
    2. Generate the consent URL (includes client_id, scopes, redirect_uri, etc.)
    3. Save the "state" and PKCE "code_verifier" in the user's session
    4. Return the URL so the view can redirect the user to Google
    
    WHY SAVE TO SESSION?
    - "state" is a random string. When Google redirects back, it includes this state.
      We compare it to detect CSRF attacks (someone tricking user into authorizing wrong app).
    - "code_verifier" is the PKCE secret. We need it in the callback to exchange the code.
      Without it, Google rejects with "Missing code verifier".
    
    PARAMETERS:
    - request: Django HttpRequest (we use request.session to store state)
    
    RETURNS:
    - URL string pointing to accounts.google.com/o/oauth2/auth?...
    """
    flow = build_flow()
    url, state = flow.authorization_url(
        # access_type="offline" means: give us a refresh_token so we can access
        # the calendar even when the user isn't actively using the app
        access_type="offline",
        # prompt="consent" means: always show the consent screen, even if user
        # previously authorized. This ensures we get a fresh refresh_token.
        prompt="consent",
        # If user previously granted some scopes, keep those too
        include_granted_scopes="true",
    )
    
    # Save state for CSRF verification in the callback
    request.session[SESSION_STATE_KEY] = state
    
    # CRITICAL: Save the PKCE code_verifier. The library generated this internally
    # when we called authorization_url(). We MUST send it back when exchanging
    # the code, or Google rejects with "Missing code verifier".
    request.session[SESSION_VERIFIER_KEY] = flow.code_verifier
    
    return url


def fetch_credentials(request):
    """
    Exchange the authorization code for access and refresh tokens.
    
    THIS IS STEP 2 OF THE OAUTH FLOW (the callback):
    1. Google redirected user back to /oauth2/callback/?code=XXX&state=YYY
    2. Verify the state matches what we saved (CSRF protection)
    3. Retrieve the PKCE code_verifier from the session
    4. Rebuild the Flow with the same state
    5. Restore the code_verifier on the Flow object
    6. Call flow.fetch_token() which POSTs to Google's token endpoint
    7. Return the credentials (access_token, refresh_token, expiry, etc.)
    
    PARAMETERS:
    - request: Django HttpRequest containing ?code=...&state=... query params
    
    RETURNS:
    - google.oauth2.credentials.Credentials object containing:
      - access_token: Short-lived token for API calls (expires in ~1 hour)
      - refresh_token: Long-lived token to get new access_tokens
      - token_uri: Where to refresh
      - client_id, client_secret: For refreshing
      - scopes: What permissions were granted
    
    RAISES:
    - OAuthConfigError if state mismatch or missing code_verifier
    """
    # Retrieve and remove state from session (pop = get + delete)
    expected_state = request.session.pop(SESSION_STATE_KEY, None)
    code_verifier = request.session.pop(SESSION_VERIFIER_KEY, None)
    received_state = request.GET.get("state")

    # CSRF check: state must match
    if not expected_state or expected_state != received_state:
        raise OAuthConfigError(
            "OAuth state mismatch. Start the flow again from the beginning; "
            "do not reuse or bookmark the callback URL."
        )

    # PKCE check: we must have the verifier
    if not code_verifier:
        raise OAuthConfigError(
            "Missing PKCE code verifier. Your session may have expired. "
            "Start the flow again from the beginning."
        )

    # Rebuild the Flow with the same state
    flow = build_flow(state=expected_state)
    
    # CRITICAL: Restore the code_verifier that was generated in authorization_url()
    # Without this, Google's token endpoint rejects with "invalid_grant: Missing code verifier"
    flow.code_verifier = code_verifier
    
    # Exchange the authorization code for tokens
    # build_absolute_uri() gives us the full URL including ?code=...&state=...
    # The library extracts the code and POSTs it to Google
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    
    return flow.credentials
