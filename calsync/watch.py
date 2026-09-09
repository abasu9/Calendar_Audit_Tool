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


def get_active_channels(calendar_id: Optional[str] = None) -> list[WatchChannel]:
    """Return active channels, optionally limited to one calendar.

    The queryset always filters on the local active flag and is evaluated into a
    list before returning it to commands or views.
    """
    queryset = WatchChannel.objects.filter(active=True)
    if calendar_id:
        queryset = queryset.filter(calendar_id=calendar_id)
    return list(queryset)


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
