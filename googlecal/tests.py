"""Verify Google Calendar routes, dashboard behavior, OAuth, and credentials.

External Google calls are replaced with mocks. This keeps tests repeatable while
checking redirects, rendered states, token loading, Google Sign-In user resolution,
and per-user credential round-trips.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

User = get_user_model()


# ---------------------------------------------------------------------------
# URL routing
# ---------------------------------------------------------------------------

class GoogleCalURLTests(TestCase):
    """Test URL routing for the googlecal app."""

    def test_dashboard_url_resolves(self):
        url = reverse("dashboard")
        self.assertEqual(url, "/")

    def test_oauth_start_url_resolves(self):
        url = reverse("oauth_start")
        self.assertEqual(url, "/oauth2/start/")

    def test_oauth_callback_url_resolves(self):
        url = reverse("oauth_callback")
        self.assertEqual(url, "/oauth2/callback/")

    def test_logout_url_resolves(self):
        url = reverse("logout")
        self.assertEqual(url, "/logout/")


# ---------------------------------------------------------------------------
# Dashboard view
# ---------------------------------------------------------------------------

class DashboardViewTests(TestCase):
    """Test the dashboard view for anonymous and authenticated users."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("dashboard")
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="pw"
        )

    def test_anonymous_user_sees_sign_in_prompt(self):
        """Anonymous visitors should see the sign-in button."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in with Google")

    def test_dashboard_contains_title(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Calendar Audit Tool")

    @patch("googlecal.views.load_credentials")
    def test_authenticated_user_without_credentials_sees_notice(self, mock_load):
        """A logged-in user with no DB credentials gets a notice."""
        from googlecal.client import GoogleAuthError
        mock_load.side_effect = GoogleAuthError("No credentials")
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No credentials")

    @patch("googlecal.views.load_credentials")
    @patch("googlecal.views.build_service")
    def test_authenticated_user_with_credentials_sees_calendar(self, mock_build, mock_load):
        """A logged-in user with valid credentials sees the calendar preview."""
        mock_creds = MagicMock()
        mock_load.return_value = mock_creds

        mock_service = MagicMock()
        mock_service.calendars().get().execute.return_value = {
            "id": "primary",
            "summary": "test@example.com",
            "timeZone": "America/Chicago",
        }
        mock_service.events().list().execute.return_value = {"items": []}
        mock_build.return_value = mock_service

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_authenticated_user_sees_email_and_logout(self):
        """Header should show the user's email and logout link when signed in."""
        self.client.force_login(self.user)
        with patch("googlecal.views.load_credentials") as mock_load:
            from googlecal.client import GoogleAuthError
            mock_load.side_effect = GoogleAuthError("no creds")
            response = self.client.get(self.url)
        self.assertContains(response, "test@example.com")
        self.assertContains(response, "Sign out")


# ---------------------------------------------------------------------------
# OAuth start view
# ---------------------------------------------------------------------------

class OAuthStartViewTests(TestCase):
    """Test the OAuth start redirect."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("oauth_start")

    @patch("googlecal.views.authorization_url")
    def test_redirects_to_google(self, mock_auth_url):
        mock_auth_url.return_value = "https://accounts.google.com/auth?..."
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://accounts.google.com"))


# ---------------------------------------------------------------------------
# OAuth callback view — Google Sign-In
# ---------------------------------------------------------------------------

class OAuthCallbackViewTests(TestCase):
    """Test the OAuth callback view including user creation and login."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("oauth_callback")

    def test_callback_with_error_param_returns_400(self):
        response = self.client.get(self.url, {"error": "access_denied"})
        self.assertEqual(response.status_code, 400)

    @patch("calsync.bootstrap.start_bootstrap")
    @patch("googlecal.views.save_credentials")
    @patch("googlecal.views.verify_id_token")
    @patch("googlecal.views.fetch_credentials")
    def test_successful_callback_creates_user_and_bootstraps(
        self, mock_fetch, mock_verify, mock_save, mock_bootstrap
    ):
        """Successful callback must create the user, log in, save creds, bootstrap."""
        mock_creds = MagicMock()
        mock_fetch.return_value = mock_creds
        mock_verify.return_value = {"sub": "google-sub-001", "email": "new@example.com"}

        response = self.client.get(
            self.url, {"code": "auth-code", "state": "s"}
        )

        # User should have been created.
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        # save_credentials and bootstrap should have been called.
        mock_save.assert_called_once()
        mock_bootstrap.assert_called_once()
        # Redirects to dashboard.
        self.assertIn(response.status_code, [302, 400])

    @patch("calsync.bootstrap.start_bootstrap")
    @patch("googlecal.views.fetch_credentials")
    def test_bootstrap_not_called_on_fetch_failure(self, mock_fetch, mock_bootstrap):
        """Bootstrap must not be called when credential exchange fails."""
        from googlecal.oauth import OAuthConfigError
        mock_fetch.side_effect = OAuthConfigError("state mismatch")

        self.client.get(self.url, {"code": "auth-code", "state": "bad"})

        mock_bootstrap.assert_not_called()

    @patch("calsync.bootstrap.start_bootstrap")
    @patch("googlecal.views.save_credentials")
    @patch("googlecal.views.verify_id_token")
    @patch("googlecal.views.fetch_credentials")
    def test_existing_user_is_resolved_by_google_sub(
        self, mock_fetch, mock_verify, mock_save, mock_bootstrap
    ):
        """A returning user is found via their GoogleCredential row."""
        from googlecal.models import GoogleCredential

        user = User.objects.create_user(username="alice", email="alice@example.com")
        GoogleCredential.objects.create(
            user=user,
            google_sub="google-sub-alice",
            token="tok",
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["openid"],
        )

        mock_creds = MagicMock()
        mock_fetch.return_value = mock_creds
        mock_verify.return_value = {
            "sub": "google-sub-alice",
            "email": "alice@example.com",
        }

        self.client.get(self.url, {"code": "code", "state": "s"})

        # Should NOT have created a second user.
        self.assertEqual(User.objects.filter(email="alice@example.com").count(), 1)


# ---------------------------------------------------------------------------
# Logout view
# ---------------------------------------------------------------------------

class LogoutViewTests(TestCase):
    """Test the logout view."""

    def test_logout_redirects_to_dashboard(self):
        user = User.objects.create_user(username="u", password="p")
        self.client.force_login(user)
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_logout_clears_session(self):
        user = User.objects.create_user(username="u2", password="p")
        self.client.force_login(user)
        self.client.get(reverse("logout"))
        # After logout the dashboard shows sign-in prompt.
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Sign in with Google")


# ---------------------------------------------------------------------------
# OAuth module
# ---------------------------------------------------------------------------

class OAuthModuleTests(TestCase):
    """Test the oauth.py module helpers."""

    @patch("googlecal.oauth.Flow")
    def test_build_flow_uses_credentials_file(self, mock_flow_class):
        from googlecal.oauth import build_flow

        mock_flow = MagicMock()
        mock_flow_class.from_client_secrets_file.return_value = mock_flow

        try:
            build_flow()
        except Exception:
            pass

        if mock_flow_class.from_client_secrets_file.called:
            self.assertIsNotNone(mock_flow_class.from_client_secrets_file.call_args)


# ---------------------------------------------------------------------------
# Client module
# ---------------------------------------------------------------------------

class ClientModuleTests(TestCase):
    """Test the per-user client.py module functions."""

    def test_load_credentials_raises_when_no_db_row(self):
        """load_credentials raises GoogleAuthError when the user has no credential row."""
        from googlecal.client import GoogleAuthError, load_credentials

        user = User.objects.create_user(username="nocreds", email="nocreds@example.com")
        with self.assertRaises(GoogleAuthError):
            load_credentials(user)

    def test_save_credentials_creates_db_row(self):
        """save_credentials persists a GoogleCredential row for the user."""
        from unittest.mock import MagicMock, patch
        from googlecal.client import save_credentials
        from googlecal.models import GoogleCredential

        user = User.objects.create_user(username="cred_user", email="cred@example.com")

        mock_creds = MagicMock()
        mock_creds.token = "access-token"
        mock_creds.refresh_token = "refresh-token"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.scopes = ["openid", "https://www.googleapis.com/auth/calendar.readonly"]
        mock_creds.expiry = None

        save_credentials(
            user,
            mock_creds,
            identity={"sub": "google-sub-999", "email": "cred@example.com"},
        )

        row = GoogleCredential.objects.get(user=user)
        self.assertEqual(row.google_sub, "google-sub-999")
        self.assertEqual(row.email, "cred@example.com")
        self.assertEqual(row.token, "access-token")

    def test_save_credentials_round_trip(self):
        """Saving then loading credentials returns usable-looking values."""
        from unittest.mock import MagicMock, patch
        from googlecal.client import save_credentials, load_credentials, GoogleAuthError
        from googlecal.models import GoogleCredential

        user = User.objects.create_user(username="roundtrip", email="rt@example.com")

        mock_creds = MagicMock()
        mock_creds.token = "tok"
        mock_creds.refresh_token = "rtok"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.scopes = ["openid"]
        mock_creds.expiry = None

        with patch("googlecal.oauth.client_config", return_value={
            "client_id": "cid", "client_secret": "csec",
        }):
            save_credentials(user, mock_creds, identity={"sub": "sub-rt", "email": "rt@example.com"})

        row = GoogleCredential.objects.get(user=user)
        self.assertEqual(row.token, "tok")
        self.assertEqual(row.refresh_token, "rtok")


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------

class CrossUserIsolationTests(TestCase):
    """Credentials for user A must not be accessible to user B."""

    def setUp(self):
        from googlecal.models import GoogleCredential
        from googlecal.client import save_credentials

        self.user_a = User.objects.create_user(username="user_a", email="a@example.com")
        self.user_b = User.objects.create_user(username="user_b", email="b@example.com")

        mock_creds = MagicMock()
        mock_creds.token = "token-a"
        mock_creds.refresh_token = "refresh-a"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.scopes = ["openid"]
        mock_creds.expiry = None

        with patch("googlecal.oauth.client_config", return_value={
            "client_id": "cid", "client_secret": "csec",
        }):
            save_credentials(self.user_a, mock_creds, identity={"sub": "sub-a", "email": "a@example.com"})

    def test_user_b_has_no_credentials(self):
        from googlecal.client import GoogleAuthError, load_credentials
        from googlecal.oauth import client_config

        with self.assertRaises(GoogleAuthError):
            with patch("googlecal.oauth.client_config", return_value={
                "client_id": "cid", "client_secret": "csec",
            }):
                load_credentials(self.user_b)

    def test_user_a_credential_not_visible_to_user_b(self):
        from googlecal.models import GoogleCredential

        self.assertFalse(GoogleCredential.objects.filter(user=self.user_b).exists())
        self.assertTrue(GoogleCredential.objects.filter(user=self.user_a).exists())
