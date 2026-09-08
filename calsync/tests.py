"""
Test cases for the calsync app.

Tests cover:
1. CalendarEvent model and parsing methods
2. SyncState model
3. WatchChannel model
4. Webhook endpoint
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import CalendarEvent, SyncState, WatchChannel


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
