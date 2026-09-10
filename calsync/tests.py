"""Verify sync models plus the manual and webhook HTTP endpoints.

Tests create isolated database records and mock synchronization where external
Google access would otherwise be required. Assertions cover parsing, saved state,
request security, notification validation, and response data.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import CalendarEvent, SyncState, WatchChannel
from .sync import SyncResult


class CalendarEventModelTests(TestCase):
    """
    Test cases for the CalendarEvent model.
    """
    
    def test_create_event(self):
        """
        Can create a basic CalendarEvent.
        """
        event = CalendarEvent.objects.create(
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
    
    def test_str_representation(self):
        """
        __str__ should return date and summary.
        """
        event = CalendarEvent.objects.create(
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
        """
        __str__ should show (no title) for events without summary.
        """
        event = CalendarEvent.objects.create(
            google_event_id="test-no-title",
            calendar_id="primary",
            summary="",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
        )
        
        self.assertIn("(no title)", str(event))


class CalendarEventFromGoogleTests(TestCase):
    """
    Test cases for CalendarEvent.from_google_event() method.
    """
    
    def test_parse_timed_event(self):
        """
        Correctly parses a timed event with dateTime.
        """
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
        
        event = CalendarEvent.from_google_event(google_event, "primary")
        
        self.assertEqual(event.google_event_id, "timed-event-123")
        self.assertEqual(event.summary, "1:1 Meeting")
        self.assertEqual(event.all_day, False)
        self.assertEqual(event.duration_minutes, 30)
        self.assertEqual(event.attendee_count, 2)
        self.assertEqual(event.organizer_email, "organizer@example.com")
        self.assertEqual(event.status, "confirmed")
    
    def test_parse_all_day_event(self):
        """
        Correctly parses an all-day event with date (not dateTime).
        """
        google_event = {
            "id": "all-day-123",
            "summary": "Company Holiday",
            "start": {"date": "2026-12-25"},
            "end": {"date": "2026-12-26"},
            "status": "confirmed",
        }
        
        event = CalendarEvent.from_google_event(google_event, "primary")
        
        self.assertEqual(event.google_event_id, "all-day-123")
        self.assertEqual(event.all_day, True)
        self.assertEqual(event.duration_minutes, 0)  # All-day = 0 duration
    
    def test_parse_event_without_summary(self):
        """
        Events without summary should default to empty string.
        """
        google_event = {
            "id": "no-summary",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
        }
        
        event = CalendarEvent.from_google_event(google_event, "primary")
        
        self.assertEqual(event.summary, "")
    
    def test_parse_event_without_attendees(self):
        """
        Events without attendees should have attendee_count=0.
        """
        google_event = {
            "id": "solo-event",
            "summary": "Focus Time",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T12:00:00Z"},
        }
        
        event = CalendarEvent.from_google_event(google_event, "primary")
        
        self.assertEqual(event.attendee_count, 0)
    
    def test_stores_raw_json(self):
        """
        The raw_json field should contain the original Google event.
        """
        google_event = {
            "id": "raw-json-test",
            "summary": "Test",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
            "customField": "customValue",
        }
        
        event = CalendarEvent.from_google_event(google_event, "primary")
        
        self.assertEqual(event.raw_json, google_event)
        self.assertEqual(event.raw_json["customField"], "customValue")


class CalendarEventParseGoogleTests(TestCase):
    """
    Test cases for CalendarEvent.parse_google_event() method.
    """
    
    def test_returns_dict(self):
        """
        parse_google_event should return a dict (not a model instance).
        """
        google_event = {
            "id": "dict-test",
            "summary": "Meeting",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
        }
        
        result = CalendarEvent.parse_google_event(google_event, "primary")
        
        self.assertIsInstance(result, dict)
    
    def test_dict_excludes_google_event_id(self):
        """
        The returned dict should not include google_event_id (it's the PK).
        """
        google_event = {
            "id": "exclude-id-test",
            "summary": "Meeting",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
        }
        
        result = CalendarEvent.parse_google_event(google_event, "primary")
        
        self.assertNotIn("google_event_id", result)
    
    def test_dict_contains_all_fields(self):
        """
        The returned dict should contain all updatable fields.
        """
        google_event = {
            "id": "fields-test",
            "summary": "Meeting",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
            "status": "confirmed",
        }
        
        result = CalendarEvent.parse_google_event(google_event, "primary")
        
        expected_fields = [
            "calendar_id", "summary", "start_time", "end_time",
            "all_day", "duration_minutes", "attendee_count",
            "organizer_email", "status", "raw_json",
        ]
        
        for field in expected_fields:
            self.assertIn(field, result)


class SyncStateModelTests(TestCase):
    """
    Test cases for the SyncState model.
    """
    
    def test_create_sync_state(self):
        """
        Can create a SyncState for a calendar.
        """
        state = SyncState.objects.create(
            calendar_id="primary",
            sync_token="token123",
        )
        
        self.assertEqual(state.calendar_id, "primary")
        self.assertEqual(state.sync_token, "token123")
    
    def test_str_representation(self):
        """
        __str__ should identify the calendar.
        """
        state = SyncState.objects.create(
            calendar_id="test@example.com",
        )
        
        self.assertIn("test@example.com", str(state))
    
    def test_unique_calendar_id(self):
        """
        calendar_id should be unique.
        """
        SyncState.objects.create(calendar_id="primary")
        
        with self.assertRaises(Exception):
            SyncState.objects.create(calendar_id="primary")


class ManualSyncViewTests(TestCase):
    """Verify the dashboard's backup synchronization endpoint."""

    def setUp(self):
        """Create a CSRF-checking client and resolve the sync URL."""

        self.client = Client(enforce_csrf_checks=True)
        self.url = reverse("manual-sync")

    def test_post_required(self):
        """Verify that a GET request cannot start synchronization."""

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_csrf_protection_is_enabled(self):
        """Verify that browser sync requests require a valid CSRF token."""

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)

    @patch("calsync.views.ensure_watch_channel")
    @patch("calsync.views.incremental_sync")
    def test_successful_sync_returns_counts(self, mock_sync, mock_ensure):
        """Verify that a successful sync returns its type and row counts."""

        mock_sync.return_value = SyncResult(
            success=True,
            full_sync=False,
            created=2,
            updated=3,
            deleted=1,
            total_events=24,
        )
        response = Client().post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "success": True,
                "sync_type": "incremental",
                "created": 2,
                "updated": 3,
                "deleted": 1,
                "total_events": 24,
            },
        )
        mock_sync.assert_called_once_with("primary")
        mock_ensure.assert_called_once_with("primary")

    @patch("calsync.views.ensure_watch_channel")
    @patch("calsync.views.incremental_sync")
    def test_failed_sync_returns_error(self, mock_sync, mock_ensure):
        """Verify that a failed sync returns its message with HTTP 502."""

        mock_sync.return_value = SyncResult(
            success=False,
            full_sync=False,
            error="Google Calendar is unavailable.",
        )
        response = Client().post(self.url)

        self.assertEqual(response.status_code, 502)
        self.assertJSONEqual(
            response.content,
            {
                "success": False,
                "error": "Google Calendar is unavailable.",
            },
        )
        # ensure_watch_channel must not run when sync fails.
        mock_ensure.assert_not_called()


class WatchChannelModelTests(TestCase):
    """
    Test cases for the WatchChannel model.
    """
    
    def test_create_watch_channel(self):
        """
        Can create a WatchChannel.
        """
        channel_uuid = uuid.uuid4()
        channel = WatchChannel.objects.create(
            channel_id=channel_uuid,
            resource_id="resource-456",
            calendar_id="primary",
            token="secret-token",
            expiration=timezone.now() + timedelta(days=7),
            webhook_url="https://example.com/webhook/",
        )
        
        self.assertEqual(channel.channel_id, channel_uuid)
        self.assertTrue(channel.active)  # Field is 'active', not 'is_active'
    
    def test_is_expired_false(self):
        """
        is_expired should return False for future expiration.
        """
        channel = WatchChannel.objects.create(
            channel_id=uuid.uuid4(),
            resource_id="resource",
            calendar_id="primary",
            expiration=timezone.now() + timedelta(days=1),
        )
        
        self.assertFalse(channel.is_expired)
    
    def test_is_expired_true(self):
        """
        is_expired should return True for past expiration.
        """
        channel = WatchChannel.objects.create(
            channel_id=uuid.uuid4(),
            resource_id="resource",
            calendar_id="primary",
            expiration=timezone.now() - timedelta(days=1),
        )
        
        self.assertTrue(channel.is_expired)
    
    def test_str_representation(self):
        """
        __str__ should show calendar_id and active status.
        """
        channel_uuid = uuid.uuid4()
        channel = WatchChannel.objects.create(
            channel_id=channel_uuid,
            resource_id="resource",
            calendar_id="user@example.com",
            expiration=timezone.now() + timedelta(days=1),
        )
        
        str_repr = str(channel)
        # The actual format is "WatchChannel(calendar_id, active/inactive)"
        self.assertIn("user@example.com", str_repr)
        self.assertIn("active", str_repr)


class WebhookViewTests(TestCase):
    """
    Test cases for the webhook endpoint.
    """
    
    def setUp(self):
        """
        Set up test client and URL.
        """
        self.client = Client()
        self.url = reverse("webhook")
        
        # Create a test watch channel for token verification
        self.channel_uuid = uuid.uuid4()
        self.channel = WatchChannel.objects.create(
            channel_id=self.channel_uuid,
            resource_id="test-resource-id",
            calendar_id="primary",
            token="test-secret-token",
            expiration=timezone.now() + timedelta(days=7),
            webhook_url="https://example.com/webhook/",
        )
    
    def test_post_required(self):
        """
        GET requests should return 405 Method Not Allowed.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
    
    def test_missing_headers_returns_400(self):
        """
        Missing required headers should return 400.
        """
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
    
    def test_sync_notification_returns_200(self):
        """
        Sync notifications (initial) should return 200.
        """
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(self.channel_uuid),
            HTTP_X_GOOG_RESOURCE_ID="test-resource-id",
            HTTP_X_GOOG_RESOURCE_STATE="sync",
        )
        
        self.assertEqual(response.status_code, 200)
    
    def test_invalid_token_returns_403(self):
        """
        Invalid token should return 403 Forbidden.
        """
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(self.channel_uuid),
            HTTP_X_GOOG_RESOURCE_ID="test-resource-id",
            HTTP_X_GOOG_RESOURCE_STATE="exists",
            HTTP_X_GOOG_CHANNEL_TOKEN="wrong-token",
        )
        
        self.assertEqual(response.status_code, 403)
    
    def test_valid_exists_notification(self):
        """
        Valid exists notification with correct token should return 200.
        Note: The actual sync may fail without Google API, but webhook returns 200.
        """
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(self.channel_uuid),
            HTTP_X_GOOG_RESOURCE_ID="test-resource-id",
            HTTP_X_GOOG_RESOURCE_STATE="exists",
            HTTP_X_GOOG_CHANNEL_TOKEN="test-secret-token",
        )
        
        # Webhook always returns 200 even if sync fails internally
        self.assertEqual(response.status_code, 200)
    
    def test_unknown_channel_returns_403(self):
        """
        Unknown channel ID should fail token verification.
        """
        unknown_uuid = uuid.uuid4()
        response = self.client.post(
            self.url,
            HTTP_X_GOOG_CHANNEL_ID=str(unknown_uuid),
            HTTP_X_GOOG_RESOURCE_ID="resource",
            HTTP_X_GOOG_RESOURCE_STATE="exists",
            HTTP_X_GOOG_CHANNEL_TOKEN="any-token",
        )
        
        self.assertEqual(response.status_code, 403)


class EnsureWatchChannelTests(TestCase):
    """Verify ensure_watch_channel reuse, renewal, and no-URL skip behaviour."""

    WEBHOOK_URL = "https://example.ngrok-free.app/api/webhook/"

    def _make_channel(self, *, expiration_offset_days=7, webhook_url=None):
        return WatchChannel.objects.create(
            channel_id=uuid.uuid4(),
            resource_id="res-123",
            calendar_id="primary",
            webhook_url=webhook_url or self.WEBHOOK_URL,
            token="tok",
            expiration=timezone.now() + timedelta(days=expiration_offset_days),
            active=True,
        )

    def test_returns_none_when_no_url_and_no_public_base_url(self):
        """When PUBLIC_BASE_URL is unset and no explicit URL given, return None."""
        from calsync.watch import ensure_watch_channel
        from django.test import override_settings

        with override_settings(PUBLIC_BASE_URL=""):
            result = ensure_watch_channel("primary")

        self.assertIsNone(result)

    def test_returns_none_when_url_is_http(self):
        """Non-HTTPS URLs must be rejected and return None."""
        from calsync.watch import ensure_watch_channel

        result = ensure_watch_channel("primary", webhook_url="http://example.com/api/webhook/")

        self.assertIsNone(result)

    def test_reuses_valid_existing_channel(self):
        """A matching, long-lived channel is returned without a Google API call."""
        from calsync.watch import ensure_watch_channel

        existing = self._make_channel(expiration_offset_days=5)

        with patch("calsync.watch.create_watch_channel") as mock_create:
            result = ensure_watch_channel("primary", webhook_url=self.WEBHOOK_URL)

        mock_create.assert_not_called()
        self.assertEqual(result, existing)

    def test_does_not_reuse_nearly_expired_channel(self):
        """A channel expiring within one day triggers renewal."""
        from calsync.watch import ensure_watch_channel

        self._make_channel(expiration_offset_days=0)  # expires "now", so active=True but expired

        new_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            resource_id="new-res",
            calendar_id="primary",
            webhook_url=self.WEBHOOK_URL,
            token="new-tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        with patch("calsync.watch.create_watch_channel", return_value=new_channel) as mock_create, \
             patch("calsync.watch.stop_watch_channel"):
            result = ensure_watch_channel("primary", webhook_url=self.WEBHOOK_URL)

        mock_create.assert_called_once()
        self.assertEqual(result, new_channel)

    def test_url_mismatch_forces_new_channel(self):
        """A channel pointing at a different URL is not reused."""
        from calsync.watch import ensure_watch_channel

        self._make_channel(
            expiration_offset_days=5,
            webhook_url="https://old.ngrok-free.app/api/webhook/",
        )

        new_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            resource_id="res",
            calendar_id="primary",
            webhook_url=self.WEBHOOK_URL,
            token="tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        with patch("calsync.watch.create_watch_channel", return_value=new_channel) as mock_create, \
             patch("calsync.watch.stop_watch_channel"):
            result = ensure_watch_channel("primary", webhook_url=self.WEBHOOK_URL)

        mock_create.assert_called_once()
        self.assertEqual(result, new_channel)

    def test_does_not_touch_channels_when_no_url(self):
        """Returning early must leave any existing channels untouched."""
        from calsync.watch import ensure_watch_channel
        from django.test import override_settings

        existing = self._make_channel()

        with override_settings(PUBLIC_BASE_URL=""):
            with patch("calsync.watch.stop_watch_channel") as mock_stop:
                ensure_watch_channel("primary")

        mock_stop.assert_not_called()
        existing.refresh_from_db()
        self.assertTrue(existing.active)


class DevWatchCommandTests(TestCase):
    """Verify dev_watch URL detection and the DEBUG guard."""

    def test_refuses_to_run_in_production(self):
        """dev_watch must raise CommandError when DEBUG is False."""
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from django.test import override_settings

        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("dev_watch")

    @patch("calsync.management.commands.dev_watch._detect_ngrok_url", return_value="")
    def test_raises_error_when_no_tunnel(self, _mock):
        """With no running ngrok and no --url, the command must fail."""
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from django.test import override_settings

        with override_settings(DEBUG=True):
            with self.assertRaises(CommandError):
                call_command("dev_watch")

    @patch("calsync.management.commands.dev_watch._detect_ngrok_url",
           return_value="https://abc.ngrok-free.app")
    @patch("calsync.management.commands.dev_watch.ensure_watch_channel")
    def test_registers_channel_from_detected_url(self, mock_ensure, _mock_detect):
        """Auto-detected ngrok URL is passed to ensure_watch_channel."""
        from django.core.management import call_command
        from django.test import override_settings

        mock_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            resource_id="res",
            calendar_id="primary",
            webhook_url="https://abc.ngrok-free.app/api/webhook/",
            token="tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        mock_ensure.return_value = mock_channel

        with override_settings(DEBUG=True):
            call_command("dev_watch")

        mock_ensure.assert_called_once_with(
            calendar_id="primary",
            webhook_url="https://abc.ngrok-free.app/api/webhook/",
        )

    @patch("calsync.management.commands.dev_watch.ensure_watch_channel")
    def test_explicit_url_overrides_detection(self, mock_ensure):
        """--url flag bypasses ngrok detection."""
        from django.core.management import call_command
        from django.test import override_settings

        mock_channel = WatchChannel(
            channel_id=uuid.uuid4(),
            resource_id="res",
            calendar_id="primary",
            webhook_url="https://custom.example.com/api/webhook/",
            token="tok",
            expiration=timezone.now() + timedelta(days=7),
            active=True,
        )
        mock_ensure.return_value = mock_channel

        with override_settings(DEBUG=True):
            call_command("dev_watch", url="https://custom.example.com")

        mock_ensure.assert_called_once_with(
            calendar_id="primary",
            webhook_url="https://custom.example.com/api/webhook/",
        )
