"""Verify sync models plus the manual and webhook HTTP endpoints.

Tests create isolated per-user database records and mock synchronization where
external Google access would otherwise be required. Assertions cover parsing,
saved state, request security, notification validation, response data, and
cross-user isolation.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CalendarEvent, SyncState, WatchChannel
from .sync import SyncResult

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username="testuser", email="test@example.com"):
    return User.objects.create_user(username=username, email=email)


# ---------------------------------------------------------------------------
# CalendarEvent model
# ---------------------------------------------------------------------------

class CalendarEventModelTests(TestCase):
    """Test CalendarEvent creation and string representation."""

    def setUp(self):
        self.user = make_user()

    def test_create_event(self):
        event = CalendarEvent.objects.create(
            user=self.user,
            google_event_id="test-123",
            calendar_id="primary",
            summary="Test Meeting",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
        self.assertEqual(event.google_event_id, "test-123")
        self.assertEqual(event.summary, "Test Meeting")
        self.assertEqual(event.duration_minutes, 60)
        self.assertEqual(event.user, self.user)

    def test_str_representation(self):
        event = CalendarEvent.objects.create(
            user=self.user,
            google_event_id="test-str",
            calendar_id="primary",
            summary="Team Standup",
            start_time=datetime(2026, 9, 8, 10, 0, tzinfo=ZoneInfo("UTC")),
            end_time=datetime(2026, 9, 8, 10, 30, tzinfo=ZoneInfo("UTC")),
            duration_minutes=30,
        )
        self.assertIn("Team Standup", str(event))
        self.assertIn("2026-09-08", str(event))

    def test_str_with_no_title(self):
        event = CalendarEvent.objects.create(
            user=self.user,
            google_event_id="test-no-title",
            calendar_id="primary",
            summary="",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
        )
        self.assertIn("(no title)", str(event))

    def test_unique_together_per_user(self):
        """Same google_event_id is allowed for two different users."""
        user2 = make_user("user2", "user2@example.com")
        CalendarEvent.objects.create(
            user=self.user,
            google_event_id="shared-id",
            calendar_id="primary",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
        )
        # This must not raise.
        CalendarEvent.objects.create(
            user=user2,
            google_event_id="shared-id",
            calendar_id="primary",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
        )
        self.assertEqual(CalendarEvent.objects.filter(google_event_id="shared-id").count(), 2)

    def test_duplicate_event_id_for_same_user_raises(self):
        """Same user cannot have two rows with the same google_event_id."""
        CalendarEvent.objects.create(
            user=self.user,
            google_event_id="dup-id",
            calendar_id="primary",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
        )
        with self.assertRaises(Exception):
            CalendarEvent.objects.create(
                user=self.user,
                google_event_id="dup-id",
                calendar_id="primary",
                start_time=timezone.now(),
                end_time=timezone.now() + timedelta(hours=1),
            )


# ---------------------------------------------------------------------------
# CalendarEvent.from_google_event
# ---------------------------------------------------------------------------

class CalendarEventFromGoogleTests(TestCase):
    """Test CalendarEvent.from_google_event() class method."""

    def setUp(self):
        self.user = make_user()

    def test_parse_timed_event(self):
        google_event = {
            "id": "timed-event-123",
            "summary": "1:1 Meeting",
            "start": {"dateTime": "2026-09-08T14:00:00-05:00"},
            "end": {"dateTime": "2026-09-08T14:30:00-05:00"},
            "status": "confirmed",
            "attendees": [
                {"email": "user1@example.com"},
                {"email": "user2@example.com"},
            ],
            "organizer": {"email": "organizer@example.com"},
        }
        event = CalendarEvent.from_google_event(google_event, "primary", user=self.user)
        self.assertEqual(event.google_event_id, "timed-event-123")
        self.assertEqual(event.summary, "1:1 Meeting")
        self.assertFalse(event.all_day)
        self.assertEqual(event.duration_minutes, 30)
        self.assertEqual(event.attendee_count, 2)
        self.assertEqual(event.organizer_email, "organizer@example.com")
        self.assertEqual(event.user, self.user)

    def test_parse_all_day_event(self):
        google_event = {
            "id": "all-day-123",
            "summary": "Company Holiday",
            "start": {"date": "2026-12-25"},
            "end": {"date": "2026-12-26"},
            "status": "confirmed",
        }
        event = CalendarEvent.from_google_event(google_event, "primary", user=self.user)
        self.assertTrue(event.all_day)
        self.assertEqual(event.duration_minutes, 0)

    def test_stores_raw_json(self):
        google_event = {
            "id": "raw-json-test",
            "summary": "Test",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
            "customField": "customValue",
        }
        event = CalendarEvent.from_google_event(google_event, "primary", user=self.user)
        self.assertEqual(event.raw_json["customField"], "customValue")


# ---------------------------------------------------------------------------
# CalendarEvent.parse_google_event
# ---------------------------------------------------------------------------

class CalendarEventParseGoogleTests(TestCase):
    """Test CalendarEvent.parse_google_event() class method."""

    def test_returns_dict(self):
        google_event = {
            "id": "dict-test",
            "summary": "Meeting",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
        }
        result = CalendarEvent.parse_google_event(google_event, "primary")
        self.assertIsInstance(result, dict)

    def test_dict_excludes_google_event_id(self):
        google_event = {
            "id": "exclude-id-test",
            "summary": "Meeting",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
        }
        result = CalendarEvent.parse_google_event(google_event, "primary")
        self.assertNotIn("google_event_id", result)

    def test_dict_contains_all_fields(self):
        google_event = {
            "id": "fields-test",
            "summary": "Meeting",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
            "status": "confirmed",
        }
        result = CalendarEvent.parse_google_event(google_event, "primary")
        for field in [
            "calendar_id", "summary", "start_time", "end_time",
            "all_day", "duration_minutes", "attendee_count",
            "organizer_email", "status", "raw_json",
        ]:
            self.assertIn(field, result)


# ---------------------------------------------------------------------------
# SyncState model
# ---------------------------------------------------------------------------

class SyncStateModelTests(TestCase):
    """Test SyncState creation and uniqueness constraints."""

    def setUp(self):
        self.user = make_user()

    def test_create_sync_state(self):
        state = SyncState.objects.create(
            user=self.user,
            calendar_id="primary",
            sync_token="token123",
        )
        self.assertEqual(state.calendar_id, "primary")
        self.assertEqual(state.sync_token, "token123")

    def test_str_representation(self):
        state = SyncState.objects.create(user=self.user, calendar_id="test@example.com")
        self.assertIn("test@example.com", str(state))

    def test_unique_together_per_user(self):
        """Same calendar_id is allowed for two different users."""
        user2 = make_user("user2", "user2@example.com")
        SyncState.objects.create(user=self.user, calendar_id="primary")
        SyncState.objects.create(user=user2, calendar_id="primary")
        self.assertEqual(SyncState.objects.filter(calendar_id="primary").count(), 2)

    def test_duplicate_calendar_for_same_user_raises(self):
        SyncState.objects.create(user=self.user, calendar_id="primary")
        with self.assertRaises(Exception):
            SyncState.objects.create(user=self.user, calendar_id="primary")


# ---------------------------------------------------------------------------
# WatchChannel model
# ---------------------------------------------------------------------------

class WatchChannelModelTests(TestCase):
    """Test WatchChannel creation, expiry, and string representation."""

    def setUp(self):
        self.user = make_user()

    def test_create_watch_channel(self):
        channel_uuid = uuid.uuid4()
        channel = WatchChannel.objects.create(
            channel_id=channel_uuid,
            user=self.user,
            resource_id="resource-456",
            calendar_id="primary",
            token="secret-token",
            expiration=timezone.now() + timedelta(days=7),
            webhook_url="https://example.com/webhook/",
        )
        self.assertEqual(channel.channel_id, channel_uuid)
        self.assertTrue(channel.active)
        self.assertEqual(channel.user, self.user)

    def test_is_expired_false(self):
        channel = WatchChannel.objects.create(
            channel_id=uuid.uuid4(),
            user=self.user,
            resource_id="resource",
            calendar_id="primary",
            token="tok",
            expiration=timezone.now() + timedelta(days=1),
            webhook_url="https://example.com/webhook/",
        )
        self.assertFalse(channel.is_expired)

    def test_is_expired_true(self):
        channel = WatchChannel.objects.create(
            channel_id=uuid.uuid4(),
            user=self.user,
            resource_id="resource",
            calendar_id="primary",
            token="tok",
            expiration=timezone.now() - timedelta(days=1),
            webhook_url="https://example.com/webhook/",
        )
        self.assertTrue(channel.is_expired)

    def test_str_representation(self):
        channel = WatchChannel.objects.create(
            channel_id=uuid.uuid4(),
            user=self.user,
            resource_id="resource",
            calendar_id="user@example.com",
            token="tok",
            expiration=timezone.now() + timedelta(days=1),
            webhook_url="https://example.com/webhook/",
        )
        self.assertIn("user@example.com", str(channel))
        self.assertIn("active", str(channel))


# ---------------------------------------------------------------------------
# Manual sync view
# ---------------------------------------------------------------------------

class ManualSyncViewTests(TestCase):
    """Verify the dashboard's backup synchronisation endpoint."""

    def setUp(self):
        self.csrf_client = Client(enforce_csrf_checks=True)
        self.url = reverse("manual-sync")
        self.user = make_user()

    def test_get_not_allowed(self):
        """GET requests must be rejected with 405."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_requires_login(self):
        """Anonymous POST must redirect to login."""
        response = self.client.post(self.url)
        self.assertIn(response.status_code, [302, 403])

    def test_csrf_protection_is_enabled(self):
        """Browser sync requests without CSRF token must fail."""
        self.csrf_client.force_login(self.user)
        response = self.csrf_client.post(self.url)
        self.assertEqual(response.status_code, 403)

    @patch("calsync.views.ensure_watch_channel")
    @patch("calsync.views.incremental_sync")
    def test_successful_sync_returns_counts(self, mock_sync, mock_ensure):
        """A successful sync returns its type and row counts."""
        mock_sync.return_value = SyncResult(
            success=True,
            full_sync=False,
            created=2,
            updated=3,
            deleted=1,
            total_events=24,
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["sync_type"], "incremental")
        self.assertEqual(data["created"], 2)
        mock_sync.assert_called_once_with(self.user, "primary")
        mock_ensure.assert_called_once_with(self.user, "primary")

    @patch("calsync.views.ensure_watch_channel")
    @patch("calsync.views.incremental_sync")
    def test_failed_sync_returns_502(self, mock_sync, mock_ensure):
        """A failed sync returns its message with HTTP 502."""
        mock_sync.return_value = SyncResult(
            success=False, full_sync=False, error="Google Calendar is unavailable."
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 502)
        mock_ensure.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook view
# ---------------------------------------------------------------------------

class WebhookViewTests(TestCase):
    """Test the webhook endpoint."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("webhook")
        self.user = make_user()
        self.channel_uuid = uuid.uuid4()
        self.channel = WatchChannel.objects.create(
            channel_id=self.channel_uuid,
            user=self.user,
            resource_id="test-resource-id",
            calendar_id="primary",
            token="test-secret-token",
            expiration=timezone.now() + timedelta(days=7),
            webhook_url="https://example.com/webhook/",
        )

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_missing_headers_returns_400(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)

    def test_sync_notification_returns_200(self):
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(self.channel_uuid),
            HTTP_X_GOOG_RESOURCE_ID="test-resource-id",
            HTTP_X_GOOG_RESOURCE_STATE="sync",
        )
        self.assertEqual(response.status_code, 200)

    def test_invalid_token_returns_403(self):
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(self.channel_uuid),
            HTTP_X_GOOG_RESOURCE_ID="test-resource-id",
            HTTP_X_GOOG_RESOURCE_STATE="exists",
            HTTP_X_GOOG_CHANNEL_TOKEN="wrong-token",
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_exists_notification_returns_200(self):
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(self.channel_uuid),
            HTTP_X_GOOG_RESOURCE_ID="test-resource-id",
            HTTP_X_GOOG_RESOURCE_STATE="exists",
            HTTP_X_GOOG_CHANNEL_TOKEN="test-secret-token",
        )
        self.assertEqual(response.status_code, 200)

    def test_unknown_channel_returns_403(self):
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(uuid.uuid4()),
            HTTP_X_GOOG_RESOURCE_ID="resource",
            HTTP_X_GOOG_RESOURCE_STATE="exists",
            HTTP_X_GOOG_CHANNEL_TOKEN="any-token",
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# ensure_watch_channel
# ---------------------------------------------------------------------------

class EnsureWatchChannelTests(TestCase):
    """Verify ensure_watch_channel reuse, renewal, and no-URL skip behaviour."""

    WEBHOOK_URL = "https://example.ngrok-free.app/api/webhook/"

    def setUp(self):
        self.user = make_user()

    def _make_channel(self, *, expiration_offset_days=7, webhook_url=None, user=None):
        return WatchChannel.objects.create(
            channel_id=uuid.uuid4(),
            user=user or self.user,
            resource_id="res-123",
            calendar_id="primary",
            webhook_url=webhook_url or self.WEBHOOK_URL,
            token="tok",
            expiration=timezone.now() + timedelta(days=expiration_offset_days),
            active=True,
        )

    def test_returns_none_when_no_url_and_no_public_base_url(self):
        from calsync.watch import ensure_watch_channel

        with override_settings(PUBLIC_BASE_URL=""):
            result = ensure_watch_channel(self.user, "primary")

        self.assertIsNone(result)

    def test_returns_none_when_url_is_http(self):
        from calsync.watch import ensure_watch_channel

        result = ensure_watch_channel(
            self.user, "primary", webhook_url="http://example.com/api/webhook/"
        )
        self.assertIsNone(result)

    def test_reuses_valid_existing_channel(self):
        from calsync.watch import ensure_watch_channel

        existing = self._make_channel(expiration_offset_days=5)

        with patch("calsync.watch.create_watch_channel") as mock_create:
            result = ensure_watch_channel(
                self.user, "primary", webhook_url=self.WEBHOOK_URL
            )

        mock_create.assert_not_called()
        self.assertEqual(result, existing)

    def test_does_not_reuse_nearly_expired_channel(self):
        from calsync.watch import ensure_watch_channel

        self._make_channel(expiration_offset_days=0)

        new_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            user=self.user,
            resource_id="new-res",
            calendar_id="primary",
            webhook_url=self.WEBHOOK_URL,
            token="new-tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        with patch("calsync.watch.create_watch_channel", return_value=new_channel), \
             patch("calsync.watch.stop_watch_channel"):
            result = ensure_watch_channel(
                self.user, "primary", webhook_url=self.WEBHOOK_URL
            )

        self.assertEqual(result, new_channel)

    def test_url_mismatch_forces_new_channel(self):
        from calsync.watch import ensure_watch_channel

        self._make_channel(
            expiration_offset_days=5,
            webhook_url="https://old.ngrok-free.app/api/webhook/",
        )

        new_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            user=self.user,
            resource_id="res",
            calendar_id="primary",
            webhook_url=self.WEBHOOK_URL,
            token="tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        with patch("calsync.watch.create_watch_channel", return_value=new_channel), \
             patch("calsync.watch.stop_watch_channel"):
            result = ensure_watch_channel(
                self.user, "primary", webhook_url=self.WEBHOOK_URL
            )

        self.assertEqual(result, new_channel)

    def test_does_not_touch_channels_when_no_url(self):
        from calsync.watch import ensure_watch_channel

        existing = self._make_channel()

        with override_settings(PUBLIC_BASE_URL=""):
            with patch("calsync.watch.stop_watch_channel") as mock_stop:
                ensure_watch_channel(self.user, "primary")

        mock_stop.assert_not_called()
        existing.refresh_from_db()
        self.assertTrue(existing.active)

    def test_user_a_channel_not_visible_to_user_b(self):
        """ensure_watch_channel for user B must not reuse user A's channel."""
        from calsync.watch import ensure_watch_channel

        user_b = make_user("user_b", "b@example.com")
        # Create a channel for self.user.
        self._make_channel(expiration_offset_days=5)

        with patch("calsync.watch.create_watch_channel") as mock_create:
            mock_create.return_value = None
            with patch("calsync.watch.stop_watch_channel"):
                ensure_watch_channel(user_b, "primary", webhook_url=self.WEBHOOK_URL)

        # create_watch_channel must be called (no reuse of user A's channel).
        mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# dev_watch management command
# ---------------------------------------------------------------------------

class DevWatchCommandTests(TestCase):
    """Verify dev_watch URL detection, DEBUG guard, and user resolution."""

    def setUp(self):
        self.user = make_user()

    def test_refuses_to_run_in_production(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("dev_watch")

    @patch("calsync.management.commands.dev_watch._detect_ngrok_url", return_value="")
    def test_raises_when_no_tunnel_and_no_url(self, _):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with override_settings(DEBUG=True):
            with self.assertRaises(CommandError):
                call_command("dev_watch", user=self.user.email)

    @patch(
        "calsync.management.commands.dev_watch._detect_ngrok_url",
        return_value="https://abc.ngrok-free.app",
    )
    @patch("calsync.management.commands.dev_watch.ensure_watch_channel")
    def test_registers_channel_from_detected_url(self, mock_ensure, _):
        from django.core.management import call_command

        mock_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            user=self.user,
            resource_id="res",
            calendar_id="primary",
            webhook_url="https://abc.ngrok-free.app/api/webhook/",
            token="tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        mock_ensure.return_value = mock_channel

        with override_settings(DEBUG=True):
            call_command("dev_watch", user=self.user.email)

        mock_ensure.assert_called_once_with(
            user=self.user,
            calendar_id="primary",
            webhook_url="https://abc.ngrok-free.app/api/webhook/",
        )

    @patch("calsync.management.commands.dev_watch.ensure_watch_channel")
    def test_explicit_url_overrides_detection(self, mock_ensure):
        from django.core.management import call_command

        mock_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            user=self.user,
            resource_id="res",
            calendar_id="primary",
            webhook_url="https://custom.example.com/api/webhook/",
            token="tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        mock_ensure.return_value = mock_channel

        with override_settings(DEBUG=True):
            call_command("dev_watch", user=self.user.email, url="https://custom.example.com")

        mock_ensure.assert_called_once_with(
            user=self.user,
            calendar_id="primary",
            webhook_url="https://custom.example.com/api/webhook/",
        )

    def test_auto_selects_single_user(self):
        """When only one user exists and --user is omitted, it is selected."""
        from django.core.management import call_command

        with override_settings(DEBUG=True):
            with patch("calsync.management.commands.dev_watch.ensure_watch_channel") as mock_ensure, \
                 patch("calsync.management.commands.dev_watch._detect_ngrok_url",
                       return_value="https://auto.ngrok-free.app"):
                mock_ensure.return_value = WatchChannel(
                    channel_id=uuid.uuid4(),
                    user=self.user,
                    resource_id="res",
                    calendar_id="primary",
                    webhook_url="https://auto.ngrok-free.app/api/webhook/",
                    token="tok",
                    expiration=timezone.now() + timedelta(days=7),
                    active=True,
                )
                call_command("dev_watch")  # no --user flag

        mock_ensure.assert_called_once()
        _, kwargs = mock_ensure.call_args
        self.assertEqual(kwargs["user"], self.user)

    def test_raises_when_multiple_users_and_no_user_flag(self):
        """Multiple users require --user to disambiguate."""
        from django.core.management import call_command
        from django.core.management.base import CommandError

        make_user("user2", "user2@example.com")

        with override_settings(DEBUG=True):
            with self.assertRaises(CommandError):
                call_command("dev_watch")

    def test_raises_when_user_email_not_found(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with override_settings(DEBUG=True):
            with self.assertRaises(CommandError):
                call_command("dev_watch", user="nobody@example.com")


# ---------------------------------------------------------------------------
# Cross-user data isolation
# ---------------------------------------------------------------------------

class CrossUserDataIsolationTests(TestCase):
    """Calendar events and sync state from user A must not appear for user B."""

    def setUp(self):
        self.user_a = make_user("user_a", "a@example.com")
        self.user_b = make_user("user_b", "b@example.com")
        now = timezone.now()
        CalendarEvent.objects.create(
            user=self.user_a,
            google_event_id="event-a",
            calendar_id="primary",
            summary="User A Meeting",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_minutes=60,
            status="confirmed",
        )

    def test_user_b_sees_no_events(self):
        events = CalendarEvent.objects.filter(user=self.user_b)
        self.assertEqual(events.count(), 0)

    def test_user_a_sees_own_events(self):
        events = CalendarEvent.objects.filter(user=self.user_a)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().summary, "User A Meeting")
