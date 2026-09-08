"""
Watch Channel Management

PURPOSE:
Manage Google Calendar push notification subscriptions (watch channels).
When events change, Google sends a POST to our webhook URL.

HOW WATCH CHANNELS WORK:

1. CREATE:
   - We call events.watch() with our webhook URL
   - Google returns a channel_id (our UUID) and resource_id (Google's ID)
   - Google sends a "sync" notification to confirm
   
2. RECEIVE NOTIFICATIONS:
   - When events change, Google POSTs to our webhook
   - Headers include channel_id and resource_id
   - Body is empty - we must call the API to get actual changes
   
3. STOP:
   - We call channels.stop() with channel_id and resource_id
   - Google stops sending notifications
   
4. EXPIRATION:
   - Channels expire (default ~1 week)
   - We must create a new channel before expiration
   - Google doesn't auto-renew

REQUIREMENTS:
- Webhook URL must be HTTPS with a valid (non-self-signed) certificate
- For local development, use ngrok or similar tunnel
- For testing without tunnel, use the mock script to simulate notifications
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
    """
    Create a new watch channel for push notifications.
    
    PARAMETERS:
    - calendar_id: Which calendar to watch (default "primary")
    - webhook_url: Where Google should send notifications (must be HTTPS)
    - expiration_days: How many days until channel expires (max ~30 days)
    
    RETURNS:
    - WatchChannel model instance if successful
    - None if failed
    
    WHAT THIS DOES:
    1. Generate a unique channel_id (UUID)
    2. Generate a secret token for verification
    3. Call events.watch() API
    4. Save the channel to our database
    5. Return the channel
    
    NOTE ON WEBHOOK URL:
    - Must be HTTPS with valid certificate
    - Google won't send to localhost directly
    - Use ngrok/cloudflared for local development
    - For testing, use simulate_push.py instead
    """
    if not webhook_url:
        logger.error("Webhook URL is required")
        return None
    
    try:
        service = build_service()
    except Exception as exc:
        logger.error(f"Failed to build Google Calendar service: {exc}")
        return None
    
    # Generate unique IDs
    channel_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)  # 256-bit random token
    
    # Calculate expiration (Google accepts Unix timestamp in milliseconds)
    expiration_dt = timezone.now() + timedelta(days=expiration_days)
    expiration_ms = int(expiration_dt.timestamp() * 1000)
    
    # Build watch request body
    watch_body = {
        "id": str(channel_id),
        "type": "web_hook",
        "address": webhook_url,
        "token": token,
        "expiration": expiration_ms,
    }
    
    logger.info(f"Creating watch channel for {calendar_id} -> {webhook_url}")
    
    try:
        # Call the watch API
        response = (
            service.events()
            .watch(calendarId=calendar_id, body=watch_body)
            .execute()
        )
        
        # Extract response data
        resource_id = response.get("resourceId", "")
        # Google may return a different expiration than requested
        actual_expiration_ms = response.get("expiration", expiration_ms)
        actual_expiration = datetime.fromtimestamp(
            actual_expiration_ms / 1000,
            tz=ZoneInfo("UTC")
        )
        
        # Save to database
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
    """
    Stop a watch channel (unsubscribe from notifications).
    
    PARAMETERS:
    - channel_id: The channel UUID to stop (string or UUID)
    
    RETURNS:
    - True if successfully stopped
    - False if failed
    
    WHAT THIS DOES:
    1. Load the channel from database
    2. Call channels.stop() API
    3. Mark channel as inactive in our database
    
    NOTE:
    Even if the API call fails (e.g., channel already expired),
    we still mark it as inactive in our database.
    """
    # Convert string to UUID if needed
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
        # Still mark as inactive locally
        channel.active = False
        channel.save()
        return False
    
    logger.info(f"Stopping watch channel: {channel_id}")
    
    try:
        # Call the stop API
        # Note: channels().stop() is a special method, not under events()
        service.channels().stop(body={
            "id": str(channel.channel_id),
            "resourceId": channel.resource_id,
        }).execute()
        
        logger.info(f"Watch channel stopped: {channel_id}")
        
    except HttpError as exc:
        # 404 means channel already expired/doesn't exist - that's fine
        if exc.resp.status == 404:
            logger.info(f"Channel already expired or doesn't exist: {channel_id}")
        else:
            logger.error(f"Google API error stopping watch channel: {exc}")
            # Still mark as inactive locally
    except Exception as exc:
        logger.exception(f"Unexpected error stopping watch channel: {exc}")
        # Still mark as inactive locally
    
    # Mark as inactive in our database
    channel.active = False
    channel.save()
    
    return True


def get_active_channels(calendar_id: Optional[str] = None) -> list[WatchChannel]:
    """
    Get all active watch channels.
    
    PARAMETERS:
    - calendar_id: Optional filter by calendar (default: all calendars)
    
    RETURNS:
    - List of active WatchChannel instances
    """
    queryset = WatchChannel.objects.filter(active=True)
    if calendar_id:
        queryset = queryset.filter(calendar_id=calendar_id)
    return list(queryset)


def cleanup_expired_channels() -> int:
    """
    Mark all expired channels as inactive.
    
    RETURNS:
    - Number of channels marked inactive
    
    NOTE:
    This doesn't call the Google API - the channels are already
    expired on Google's side. We just update our database.
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
    """
    Verify that a push notification has the correct token.
    
    PARAMETERS:
    - channel_id: The channel UUID from X-Goog-Channel-ID header
    - token: The token from X-Goog-Channel-Token header
    
    RETURNS:
    - True if token matches our stored token
    - False if invalid or channel not found
    
    WHY VERIFY?
    Anyone could POST to our webhook URL. The token proves the
    request came from Google (we gave Google the token when creating
    the channel, and Google echoes it back in notifications).
    """
    try:
        if isinstance(channel_id, str):
            channel_id = uuid.UUID(channel_id)
        channel = WatchChannel.objects.get(channel_id=channel_id, active=True)
    except (ValueError, WatchChannel.DoesNotExist):
        return False
    
    # Constant-time comparison to prevent timing attacks
    return secrets.compare_digest(channel.token, token)
