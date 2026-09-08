"""
Calendar Sync Models

PURPOSE:
Database models for storing calendar events and managing sync state.
These enable incremental synchronization with Google Calendar.

MODELS:
- CalendarEvent: Individual calendar events fetched from Google
- SyncState: Tracks the syncToken for incremental fetches
- WatchChannel: Tracks active push notification subscriptions

HOW INCREMENTAL SYNC WORKS:
1. First sync: Fetch all events, Google returns a syncToken
2. Store the syncToken in SyncState
3. Next sync: Pass the syncToken, Google only returns changes since then
4. If syncToken expires (410 Gone), do a full sync again
"""

import uuid

from django.db import models
from django.utils import timezone


class CalendarEvent(models.Model):
    """
    A single calendar event fetched from Google Calendar.
    
    WHY STORE EVENTS LOCALLY?
    - Faster queries for audit reports (no API calls)
    - Can analyze historical data even if events are deleted from Google
    - Reduces API quota usage
    
    GOOGLE EVENT ID:
    Google's event IDs are stable and unique per calendar. We use them as
    our primary key to enable upsert operations (create or update).
    
    ALL-DAY VS TIMED EVENTS:
    - Timed events have start_time and end_time as datetimes
    - All-day events have them as dates (stored as midnight UTC)
    - The all_day flag distinguishes them
    """
    
    # Primary key: Google's event ID (stable, unique per calendar)
    google_event_id = models.CharField(
        max_length=1024,
        primary_key=True,
        help_text="Google's unique event identifier"
    )
    
    # Which calendar this event belongs to
    # Usually "primary" but could be a specific calendar email
    calendar_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Calendar ID (usually 'primary')"
    )
    
    # Event details
    summary = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Event title/summary"
    )
    
    # Start and end times
    # For all-day events, these are dates stored as midnight UTC
    start_time = models.DateTimeField(
        db_index=True,
        help_text="Event start time (UTC)"
    )
    end_time = models.DateTimeField(
        help_text="Event end time (UTC)"
    )
    
    # Flag for all-day events (which have date instead of dateTime)
    all_day = models.BooleanField(
        default=False,
        help_text="True if this is an all-day event"
    )
    
    # Computed duration in minutes (0 for all-day events in metrics)
    duration_minutes = models.IntegerField(
        default=0,
        help_text="Duration in minutes (computed from start/end)"
    )
    
    # Meeting metadata
    attendee_count = models.IntegerField(
        default=0,
        help_text="Number of attendees"
    )
    organizer_email = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Organizer's email address"
    )
    
    # Event status from Google
    # Values: "confirmed", "tentative", "cancelled"
    status = models.CharField(
        max_length=50,
        default="confirmed",
        db_index=True,
        help_text="Event status (confirmed/tentative/cancelled)"
    )
    
    # Store the full Google response for future use
    # This lets us extract additional fields later without re-syncing
    raw_json = models.JSONField(
        default=dict,
        help_text="Full event data from Google API"
    )
    
    # Timestamps for our records
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When we first synced this event"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When we last updated this event"
    )
    
    class Meta:
        ordering = ["-start_time"]
        indexes = [
            # For querying events in a time range
            models.Index(fields=["calendar_id", "start_time"]),
            # For finding events by status
            models.Index(fields=["calendar_id", "status"]),
        ]
    
    def __str__(self):
        return f"{self.start_time.date()} - {self.summary or '(no title)'}"
    
    @classmethod
    def from_google_event(cls, event: dict, calendar_id: str) -> "CalendarEvent":
        """
        Create or update a CalendarEvent from a Google API response.
        
        PARAMETERS:
        - event: Dict from Google's events.list() response
        - calendar_id: Which calendar this came from
        
        RETURNS:
        - CalendarEvent instance (not yet saved)
        
        GOOGLE EVENT STRUCTURE:
        {
            "id": "abc123",
            "summary": "Team Meeting",
            "start": {"dateTime": "2024-01-01T09:00:00-06:00"} or {"date": "2024-01-01"},
            "end": {"dateTime": "2024-01-01T10:00:00-06:00"} or {"date": "2024-01-02"},
            "status": "confirmed",
            "attendees": [...],
            "organizer": {"email": "..."},
            ...
        }
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        # Parse start time
        start_data = event.get("start", {})
        if "dateTime" in start_data:
            # Timed event
            start_time = datetime.fromisoformat(start_data["dateTime"])
            all_day = False
        else:
            # All-day event: "date" is like "2024-01-01"
            date_str = start_data.get("date", "")
            start_time = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo("UTC")
            )
            all_day = True
        
        # Parse end time
        end_data = event.get("end", {})
        if "dateTime" in end_data:
            end_time = datetime.fromisoformat(end_data["dateTime"])
        else:
            date_str = end_data.get("date", "")
            end_time = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo("UTC")
            )
        
        # Ensure times are UTC
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(ZoneInfo("UTC"))
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(ZoneInfo("UTC"))
        
        # Calculate duration (0 for all-day events)
        if all_day:
            duration_minutes = 0
        else:
            duration_minutes = int((end_time - start_time).total_seconds() // 60)
        
        # Extract attendees
        attendees = event.get("attendees") or []
        attendee_count = len(attendees)
        
        # Extract organizer
        organizer = event.get("organizer") or {}
        organizer_email = organizer.get("email", "")
        
        return cls(
            google_event_id=event["id"],
            calendar_id=calendar_id,
            summary=event.get("summary", ""),
            start_time=start_time,
            end_time=end_time,
            all_day=all_day,
            duration_minutes=duration_minutes,
            attendee_count=attendee_count,
            organizer_email=organizer_email,
            status=event.get("status", "confirmed"),
            raw_json=event,
        )
    
    @classmethod
    def parse_google_event(cls, event: dict, calendar_id: str) -> dict:
        """
        Parse a Google Calendar event into a dict of field values.
        
        Unlike from_google_event(), this returns a dict suitable for
        update_or_create(defaults=...), which properly handles
        auto_now_add fields like created_at.
        
        PARAMETERS:
        - event: Dict from Google's events.list() response
        - calendar_id: Which calendar this came from
        
        RETURNS:
        - Dict of field names to values (excludes google_event_id)
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        # Parse start time
        start_data = event.get("start", {})
        if "dateTime" in start_data:
            start_time = datetime.fromisoformat(start_data["dateTime"])
            all_day = False
        else:
            date_str = start_data.get("date", "")
            start_time = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo("UTC")
            )
            all_day = True
        
        # Parse end time
        end_data = event.get("end", {})
        if "dateTime" in end_data:
            end_time = datetime.fromisoformat(end_data["dateTime"])
        else:
            date_str = end_data.get("date", "")
            end_time = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo("UTC")
            )
        
        # Ensure times are UTC
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(ZoneInfo("UTC"))
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(ZoneInfo("UTC"))
        
        # Calculate duration (0 for all-day events)
        if all_day:
            duration_minutes = 0
        else:
            duration_minutes = int((end_time - start_time).total_seconds() // 60)
        
        # Extract attendees
        attendees = event.get("attendees") or []
        attendee_count = len(attendees)
        
        # Extract organizer
        organizer = event.get("organizer") or {}
        organizer_email = organizer.get("email", "")
        
        # Return dict of defaults (excludes primary key)
        return {
            "calendar_id": calendar_id,
            "summary": event.get("summary", ""),
            "start_time": start_time,
            "end_time": end_time,
            "all_day": all_day,
            "duration_minutes": duration_minutes,
            "attendee_count": attendee_count,
            "organizer_email": organizer_email,
            "status": event.get("status", "confirmed"),
            "raw_json": event,
        }


class SyncState(models.Model):
    """
    Tracks the sync state for incremental synchronization.
    
    WHAT IS A SYNC TOKEN?
    When you call events.list() on Google Calendar, the response includes
    a "nextSyncToken". On subsequent calls, pass this token and Google
    only returns events that changed since then.
    
    WHY TRACK THIS?
    - Dramatically reduces API calls and data transfer
    - Enables near-instant updates when combined with push notifications
    - Required for "instantaneous" sync requirement
    
    TOKEN EXPIRATION:
    Sync tokens can expire (Google returns 410 Gone). When this happens,
    we do a full sync to re-establish the baseline.
    """
    
    # Which calendar this sync state is for
    calendar_id = models.CharField(
        max_length=255,
        primary_key=True,
        help_text="Calendar ID (usually 'primary')"
    )
    
    # Google's sync token for incremental fetches
    sync_token = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Google's syncToken for incremental sync"
    )
    
    # When we last did a full sync (fetched everything)
    last_full_sync = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When we last did a complete sync"
    )
    
    # When we last synced (full or incremental)
    last_sync = models.DateTimeField(
        auto_now=True,
        help_text="When we last synced (any type)"
    )
    
    def __str__(self):
        return f"SyncState({self.calendar_id})"


class WatchChannel(models.Model):
    """
    Tracks active push notification subscriptions (watch channels).
    
    HOW PUSH NOTIFICATIONS WORK:
    1. We call events.watch() with our webhook URL
    2. Google returns a channel_id and resource_id
    3. When events change, Google POSTs to our webhook with these IDs
    4. We verify the request and trigger an incremental sync
    
    CHANNEL EXPIRATION:
    Channels expire (default ~1 week). We need to renew them before expiry.
    Google doesn't auto-renew - we must create a new channel.
    
    SECURITY:
    We generate a random token and include it in the watch request.
    Google echoes it back in notifications. We verify it matches to
    prevent spoofed notifications.
    """
    
    # Our UUID for this channel (sent to Google, echoed back in notifications)
    channel_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        help_text="Our UUID for this watch channel"
    )
    
    # Google's resource ID (returned by watch, needed to stop the channel)
    resource_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Google's resource ID for this channel"
    )
    
    # Which calendar we're watching
    calendar_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Calendar ID being watched"
    )
    
    # Where notifications are sent
    webhook_url = models.URLField(
        help_text="Webhook URL for notifications"
    )
    
    # Secret token for verification (we generate, Google echoes back)
    token = models.CharField(
        max_length=256,
        help_text="Secret token to verify notifications"
    )
    
    # When this channel expires
    expiration = models.DateTimeField(
        help_text="When this channel expires"
    )
    
    # Whether we're actively using this channel
    active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this channel is active"
    )
    
    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When we created this channel"
    )
    
    class Meta:
        ordering = ["-created_at"]
    
    def __str__(self):
        status = "active" if self.active else "inactive"
        return f"WatchChannel({self.calendar_id}, {status})"
    
    @property
    def is_expired(self) -> bool:
        """Check if this channel has expired."""
        return timezone.now() >= self.expiration
