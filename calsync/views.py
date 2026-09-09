"""
Calendar Sync Views

PURPOSE:
HTTP endpoints for the calendar sync system:
- Manual sync endpoint used by the dashboards
- Webhook endpoint that receives Google push notifications
- Status/info endpoints (future)

GOOGLE PUSH NOTIFICATIONS:
When calendar events change, Google POSTs to our webhook URL with these headers:
- X-Goog-Channel-ID: Our UUID for the channel
- X-Goog-Resource-ID: Google's ID for the resource
- X-Goog-Resource-State: "sync" (initial) or "exists" (changes)
- X-Goog-Channel-Token: Our secret verification token
- X-Goog-Message-Number: Incrementing message number

The body is EMPTY - we must call the API to get actual changes.

IMPORTANT NOTES:
1. Must respond quickly (within seconds) or Google will retry
2. Must return 2xx status - 5xx causes retries with exponential backoff
3. CSRF exempt - Google can't send Django's CSRF token
4. Token verification prevents spoofed notifications
"""

import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .sync import handle_push_notification, incremental_sync
from .watch import verify_notification_token

logger = logging.getLogger(__name__)


@require_POST
def manual_sync(request):
    """Synchronize the primary calendar when requested from the dashboard."""
    result = incremental_sync("primary")

    if not result.success:
        return JsonResponse(
            {
                "success": False,
                "error": result.error or "Calendar sync failed.",
            },
            status=502,
        )

    return JsonResponse(
        {
            "success": True,
            "sync_type": "full" if result.full_sync else "incremental",
            "created": result.created,
            "updated": result.updated,
            "deleted": result.deleted,
            "total_events": result.total_events,
        }
    )


@csrf_exempt  # Google can't send CSRF tokens
@require_POST
def webhook(request):
    """
    Receive push notifications from Google Calendar.
    
    WHAT GOOGLE SENDS:
    - POST request to our webhook URL
    - Headers contain channel info and state
    - Body is empty (no event data!)
    
    HEADERS:
    - X-Goog-Channel-ID: UUID we provided when creating the channel
    - X-Goog-Resource-ID: Google's ID for the watched resource
    - X-Goog-Resource-State: "sync" or "exists"
    - X-Goog-Channel-Token: Secret token for verification
    - X-Goog-Message-Number: Incrementing number (not sequential)
    - X-Goog-Channel-Expiration: When channel expires (human readable)
    
    RESOURCE STATES:
    - "sync": Initial notification after creating a watch channel
             We don't need to sync - just acknowledge
    - "exists": Resource changed (created, updated, or deleted)
               We need to call incremental_sync() to get changes
    
    RETURNS:
    - 200 OK on success (Google needs this)
    - 400 Bad Request if missing required headers
    - 403 Forbidden if token verification fails
    """
    # Extract headers
    channel_id = request.headers.get("X-Goog-Channel-ID", "")
    resource_id = request.headers.get("X-Goog-Resource-ID", "")
    resource_state = request.headers.get("X-Goog-Resource-State", "")
    token = request.headers.get("X-Goog-Channel-Token", "")
    message_number = request.headers.get("X-Goog-Message-Number", "")
    
    logger.info(
        f"Webhook received: channel={channel_id}, state={resource_state}, "
        f"message={message_number}"
    )
    
    # Validate required headers
    if not channel_id or not resource_state:
        logger.warning("Webhook missing required headers")
        return HttpResponse("Missing required headers", status=400)
    
    # Handle sync message (initial notification)
    if resource_state == "sync":
        logger.info(f"Received sync notification for channel {channel_id}")
        return HttpResponse("OK", status=200)
    
    # Verify token to prevent spoofed notifications
    if not verify_notification_token(channel_id, token):
        logger.warning(f"Token verification failed for channel {channel_id}")
        return HttpResponse("Invalid token", status=403)
    
    # Handle the notification (triggers incremental sync)
    if resource_state == "exists":
        result = handle_push_notification(channel_id, resource_id)
        
        if result.success:
            logger.info(
                f"Push sync complete: +{result.created} ~{result.updated} "
                f"-{result.deleted}"
            )
        else:
            # Log error but still return 200 - don't want Google to retry
            # The sync can catch up on the next notification or manual request
            logger.error(f"Push sync failed: {result.error}")
    
    # Always return 200 to prevent retries
    # If sync failed, it will catch up on next notification
    return HttpResponse("OK", status=200)
