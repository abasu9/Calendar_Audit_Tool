"""Run Google's server-side OAuth authorization-code flow.

The start request builds a consent URL and stores CSRF state plus a PKCE verifier
in the session. The callback validates both values and exchanges Google's short-
lived code for credentials that can call Calendar APIs.
"""

import json
import logging

from django.conf import settings
from google_auth_oauthlib.flow import Flow

logger = logging.getLogger(__name__)

# Session values connect the authorization start and callback requests.
SESSION_STATE_KEY = "google_oauth_state"
SESSION_VERIFIER_KEY = "google_oauth_code_verifier"


class OAuthConfigError(RuntimeError):
    """Report invalid OAuth configuration or callback session state."""

    pass


def client_type():
    """Return whether the configured OAuth client is web or installed.

    Google's client JSON is parsed and its top-level ``web`` or ``installed`` key
    is returned. Missing files, invalid JSON, and unrelated credential formats
    raise ``OAuthConfigError`` with setup guidance.
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
    """Create a Google OAuth flow from the project's configured values.

    The client file is validated first, then scopes, redirect URI, and optional
    callback state are supplied to Google's flow object.
    """
    client_type()
    return Flow.from_client_secrets_file(
        str(settings.GOOGLE_CREDENTIALS_FILE),
        scopes=settings.GOOGLE_OAUTH_SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        state=state,
    )


def authorization_url(request):
    """Return Google's consent URL and save values needed by the callback.

    Offline access requests a refresh token. Random state protects against forged
    callbacks, while the PKCE verifier proves that the callback belongs to this
    browser session; both are stored until ``fetch_credentials`` consumes them.
    """
    flow = build_flow()
    url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    request.session[SESSION_STATE_KEY] = state
    request.session[SESSION_VERIFIER_KEY] = flow.code_verifier
    
    return url


def fetch_credentials(request):
    """Validate Google's callback and exchange its code for credentials.

    Saved session values are removed so they cannot be reused. Matching state and
    a present PKCE verifier are required before the flow sends the complete callback
    URL to Google's token endpoint.
    """
    expected_state = request.session.pop(SESSION_STATE_KEY, None)
    code_verifier = request.session.pop(SESSION_VERIFIER_KEY, None)
    received_state = request.GET.get("state")

    if not expected_state or expected_state != received_state:
        raise OAuthConfigError(
            "OAuth state mismatch. Start the flow again from the beginning; "
            "do not reuse or bookmark the callback URL."
        )

    if not code_verifier:
        raise OAuthConfigError(
            "Missing PKCE code verifier. Your session may have expired. "
            "Start the flow again from the beginning."
        )

    flow = build_flow(state=expected_state)

    flow.code_verifier = code_verifier
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    
    return flow.credentials
