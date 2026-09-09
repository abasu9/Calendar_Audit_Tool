"""Store synchronized events, sync progress, and webhook subscriptions.

``CalendarEvent`` supplies local data for reports, ``SyncState`` remembers where
incremental syncing stopped, and ``WatchChannel`` records the subscriptions that
allow Google to notify the application about changes.
"""

import uuid

from django.db import models
from django.utils import timezone


class CalendarEvent(models.Model):
    """Represent one Google Calendar event in the local database.

    Local records make audit queries fast and reduce repeated API calls. Google's
    event ID is the primary key so later syncs can update the same row. All-day
    dates are stored at midnight UTC and marked with ``all_day``.
    """

    # Stable Google ID used to insert or update the same event.
    google_event_id = models.CharField(
        max_length=1024,
        primary_key=True,
        help_text="Google's unique event identifier"
    )
    
    # Calendar that owns this event, normally ``primary``.
    calendar_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Calendar ID (usually 'primary')"
    )
    
    summary = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Event title/summary"
    )
    
    # Timed values use UTC; all-day dates use midnight UTC.
    start_time = models.DateTimeField(
        db_index=True,
        help_text="Event start time (UTC)"
    )
    end_time = models.DateTimeField(
        help_text="Event end time (UTC)"
    )
    
    all_day = models.BooleanField(
        default=False,
        help_text="True if this is an all-day event"
    )
    
    # Reports treat all-day events as zero meeting minutes.
    duration_minutes = models.IntegerField(
        default=0,
        help_text="Duration in minutes (computed from start/end)"
    )
    
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
    
    # Google reports confirmed, tentative, or cancelled status.
    status = models.CharField(
        max_length=50,
        default="confirmed",
        db_index=True,
        help_text="Event status (confirmed/tentative/cancelled)"
    )
    
    # Preserve fields that are not yet represented as model columns.
    raw_json = models.JSONField(
        default=dict,
        help_text="Full event data from Google API"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When we first synced this event"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When we last updated this event"
    )
    
    class Meta:
        """Keep recent events first and index common report filters."""

        ordering = ["-start_time"]
        indexes = [
            models.Index(fields=["calendar_id", "start_time"]),
            models.Index(fields=["calendar_id", "status"]),
        ]

    def __str__(self):
        """Return a readable date and title for logs and admin pages."""

        return f"{self.start_time.date()} - {self.summary or '(no title)'}"

    @classmethod
    def from_google_event(cls, event: dict, calendar_id: str) -> "CalendarEvent":
        """Build an unsaved model instance from one Google event.

        The method accepts Google's timed or all-day format, converts values to
        UTC, calculates timed duration, and copies attendee and organizer details
        into the model fields.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
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
        
        end_data = event.get("end", {})
        if "dateTime" in end_data:
            end_time = datetime.fromisoformat(end_data["dateTime"])
        else:
            date_str = end_data.get("date", "")
            end_time = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo("UTC")
            )
        
        # Normalize timestamps so report queries compare one timezone.
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(ZoneInfo("UTC"))
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(ZoneInfo("UTC"))
        
        if all_day:
            duration_minutes = 0
        else:
            duration_minutes = int((end_time - start_time).total_seconds() // 60)
        
        attendees = event.get("attendees") or []
        attendee_count = len(attendees)
        
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
        """Convert one Google event into values for ``update_or_create``.

        It performs the same time and metadata conversion as
        ``from_google_event`` but excludes the primary key. Django can therefore
        update an existing row without changing its original creation time.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
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
        
        end_data = event.get("end", {})
        if "dateTime" in end_data:
            end_time = datetime.fromisoformat(end_data["dateTime"])
        else:
            date_str = end_data.get("date", "")
            end_time = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo("UTC")
            )
        
        # Normalize timestamps so report queries compare one timezone.
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(ZoneInfo("UTC"))
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(ZoneInfo("UTC"))
        
        if all_day:
            duration_minutes = 0
        else:
            duration_minutes = int((end_time - start_time).total_seconds() // 60)
        
        attendees = event.get("attendees") or []
        attendee_count = len(attendees)
        
        organizer = event.get("organizer") or {}
        organizer_email = organizer.get("email", "")
        
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
    """Remember incremental sync progress for one calendar.

    Google returns a sync token after listing events. Saving it lets the next
    request fetch only changes. If Google expires the token, the sync engine
    creates a fresh state through a full sync.
    """

    calendar_id = models.CharField(
        max_length=255,
        primary_key=True,
        help_text="Calendar ID (usually 'primary')"
    )
    
    sync_token = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Google's syncToken for incremental sync"
    )
    
    last_full_sync = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When we last did a complete sync"
    )
    
    last_sync = models.DateTimeField(
        auto_now=True,
        help_text="When we last synced (any type)"
    )
    
    def __str__(self):
        """Return the calendar ID represented by this state."""

        return f"SyncState({self.calendar_id})"


class WatchChannel(models.Model):
    """Represent one Google push-notification subscription.

    The record joins the channel ID sent in each webhook to Google's resource ID,
    the watched calendar, and a secret verification token. Expiration and active
    fields show whether the subscription should still be trusted.
    """

    # Application-generated ID that Google returns in each notification.
    channel_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        help_text="Our UUID for this watch channel"
    )
    
    # Google-generated ID required when stopping the subscription.
    resource_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Google's resource ID for this channel"
    )
    
    calendar_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Calendar ID being watched"
    )
    
    webhook_url = models.URLField(
        help_text="Webhook URL for notifications"
    )
    
    # Shared secret echoed by Google and checked with constant-time comparison.
    token = models.CharField(
        max_length=256,
        help_text="Secret token to verify notifications"
    )
    
    expiration = models.DateTimeField(
        help_text="When this channel expires"
    )
    
    active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this channel is active"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When we created this channel"
    )
    
    class Meta:
        """Show newly created subscriptions first."""

        ordering = ["-created_at"]

    def __str__(self):
        """Return the watched calendar and current local state."""

        status = "active" if self.active else "inactive"
        return f"WatchChannel({self.calendar_id}, {status})"

    @property
    def is_expired(self) -> bool:
        """Return whether the saved expiration time has passed."""

        return timezone.now() >= self.expiration
