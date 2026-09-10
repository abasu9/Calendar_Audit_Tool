"""Create, stop, inspect, and verify Google webhook subscriptions.

Google sends event-change notices to the public URL saved in each watch channel.
These helpers manage both Google's subscription and the matching database record.
Channels expire and must be created again when a new callback is needed.
"""

import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from googleapiclient.errors import HttpError

from googlecal.client import build_service
from .models import WatchChannel

logger = logging.getLogger(__name__)


def create_watch_channel(
    calendar_id: str = "primary",
    webhook_url: str = "",
    expiration_days: int = 7,
) -> Optional[WatchChannel]:
    """Register a webhook channel for one Google calendar.

    A unique ID and secret token are sent with the callback URL and requested
    expiration. Google's resource ID and actual expiration are then saved. The
    function returns ``None`` when input, authentication, or registration fails.
    """
    if not webhook_url:
        logger.error("Webhook URL is required")
        return None
    
    try:
        service = build_service()
    except Exception as exc:
        logger.error(f"Failed to build Google Calendar service: {exc}")
        return None
    
    channel_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)

    # Google expects the requested expiration as Unix milliseconds.
    expiration_dt = timezone.now() + timedelta(days=expiration_days)
    expiration_ms = int(expiration_dt.timestamp() * 1000)
    
    watch_body = {
        "id": str(channel_id),
        "type": "web_hook",
        "address": webhook_url,
        "token": token,
        "expiration": expiration_ms,
    }
    
    logger.info(f"Creating watch channel for {calendar_id} -> {webhook_url}")
    
    try:
        response = (
            service.events()
            .watch(calendarId=calendar_id, body=watch_body)
            .execute()
        )
        
        resource_id = response.get("resourceId", "")
        # Store Google's actual expiration, which may differ from the request.
        actual_expiration_ms = int(response.get("expiration", expiration_ms))
        actual_expiration = datetime.fromtimestamp(
            actual_expiration_ms / 1000,
            tz=ZoneInfo("UTC")
        )
        
        channel = WatchChannel.objects.create(
            channel_id=channel_id,
            resource_id=resource_id,
            calendar_id=calendar_id,
            webhook_url=webhook_url,
            token=token,
            expiration=actual_expiration,
            active=True,
        )
        
        logger.info(
            f"Watch channel created: {channel_id}, "
            f"expires {actual_expiration.isoformat()}"
        )
        
        return channel
        
    except HttpError as exc:
        logger.error(f"Google API error creating watch channel: {exc}")
        return None
    except Exception as exc:
        logger.exception(f"Unexpected error creating watch channel: {exc}")
        return None


def stop_watch_channel(channel_id: str) -> bool:
    """Stop one Google subscription and deactivate its local record.

    String IDs are validated as UUIDs before lookup. The channel is marked
    inactive even when Google has already removed it or the API call fails, so
    future notifications are no longer accepted locally.
    """
    if isinstance(channel_id, str):
        try:
            channel_id = uuid.UUID(channel_id)
        except ValueError:
            logger.error(f"Invalid channel ID format: {channel_id}")
            return False
    
    try:
        channel = WatchChannel.objects.get(channel_id=channel_id)
    except WatchChannel.DoesNotExist:
        logger.error(f"Channel not found: {channel_id}")
        return False
    
    if not channel.active:
        logger.info(f"Channel already inactive: {channel_id}")
        return True
    
    try:
        service = build_service()
    except Exception as exc:
        logger.error(f"Failed to build Google Calendar service: {exc}")
        # Do not leave an unusable local subscription marked active.
        channel.active = False
        channel.save()
        return False
    
    logger.info(f"Stopping watch channel: {channel_id}")
    
    try:
        # Stopping a channel uses the top-level channels API.
        service.channels().stop(body={
            "id": str(channel.channel_id),
            "resourceId": channel.resource_id,
        }).execute()
        
        logger.info(f"Watch channel stopped: {channel_id}")
        
    except HttpError as exc:
        # A missing remote channel is already stopped for practical purposes.
        if exc.resp.status == 404:
            logger.info(f"Channel already expired or doesn't exist: {channel_id}")
        else:
            logger.error(f"Google API error stopping watch channel: {exc}")
    except Exception as exc:
        logger.exception(f"Unexpected error stopping watch channel: {exc}")

    channel.active = False
    channel.save()
    
    return True



def cleanup_expired_channels() -> int:
    """Mark locally active channels with past expirations as inactive.

    Google already stops expired channels, so one database update is enough. The
    returned count lets callers report how many records changed.
    """
    now = timezone.now()
    result = WatchChannel.objects.filter(
        active=True,
        expiration__lt=now,
    ).update(active=False)
    
    if result > 0:
        logger.info(f"Marked {result} expired channels as inactive")
    
    return result


def ensure_watch_channel(
    calendar_id: str = "primary",
    webhook_url: Optional[str] = None,
) -> Optional[WatchChannel]:
    """Ensure an active, unexpired push channel exists for one calendar.

    Resolves the webhook URL from the explicit argument or from
    ``settings.PUBLIC_BASE_URL``. When no usable HTTPS URL is available the
    function logs the reason and returns ``None`` without touching any existing
    channels — this matters in local development where an ngrok channel may have
    been registered by ``dev_watch`` while ``PUBLIC_BASE_URL`` is unset.

    An active channel whose stored URL matches and whose expiration is more than
    one day away is reused. Otherwise stale channels for the calendar are stopped
    and a fresh one is created.
    """
    # Resolve the webhook URL.
    if not webhook_url:
        base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
        if not base:
            logger.info(
                "PUBLIC_BASE_URL is not set; skipping watch-channel setup for %s",
                calendar_id,
            )
            return None
        webhook_url = base + reverse("webhook")

    if not webhook_url.startswith("https://"):
        logger.warning(
            "Webhook URL %r is not HTTPS; Google cannot deliver notifications. "
            "Skipping watch-channel setup for %s.",
            webhook_url,
            calendar_id,
        )
        return None

    # Mark any channels whose expiration has already passed.
    cleanup_expired_channels()

    # Reuse an active channel for this calendar that still points at the right
    # URL and has more than one day of life remaining.
    renew_threshold = timezone.now() + timedelta(days=1)
    existing = (
        WatchChannel.objects.filter(
            calendar_id=calendar_id,
            webhook_url=webhook_url,
            active=True,
            expiration__gt=renew_threshold,
        )
        .order_by("-expiration")
        .first()
    )
    if existing:
        logger.info(
            "Reusing existing watch channel %s for %s (expires %s)",
            existing.channel_id,
            calendar_id,
            existing.expiration.isoformat(),
        )
        return existing

    # Stop any stale channels for this calendar before creating a new one.
    stale = WatchChannel.objects.filter(calendar_id=calendar_id, active=True)
    for ch in stale:
        stop_watch_channel(str(ch.channel_id))

    channel = create_watch_channel(
        calendar_id=calendar_id,
        webhook_url=webhook_url,
        expiration_days=getattr(settings, "WATCH_EXPIRATION_DAYS", 7),
    )
    if channel:
        logger.info(
            "Created new watch channel %s for %s",
            channel.channel_id,
            calendar_id,
        )
    else:
        logger.error("Failed to create watch channel for %s", calendar_id)
    return channel


def verify_notification_token(channel_id: str, token: str) -> bool:
    """Check a notification token against its active saved channel.

    Invalid UUIDs and unknown channels are rejected. Valid tokens are compared in
    constant time so response timing does not reveal the saved secret.
    """
    try:
        if isinstance(channel_id, str):
            channel_id = uuid.UUID(channel_id)
        channel = WatchChannel.objects.get(channel_id=channel_id, active=True)
    except (ValueError, WatchChannel.DoesNotExist):
        return False
    
    return secrets.compare_digest(channel.token, token)
