"""Provide manual and webhook entry points for calendar synchronization.

Dashboard users may request a backup sync. Google calls the webhook when calendar
data changes; the endpoint validates notification headers and then retrieves the
actual changes because notification bodies contain no event data.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .sync import handle_push_notification, incremental_sync
from .watch import ensure_watch_channel, verify_notification_token

logger = logging.getLogger(__name__)


@login_required
@require_POST
def manual_sync(request):
    """Synchronize the primary calendar after a dashboard request.

    The standard incremental engine runs immediately and falls back to a full sync
    when needed. Its success state and row counts are returned as JSON.
    """
    result = incremental_sync(request.user, "primary")

    if not result.success:
        return JsonResponse(
            {
                "success": False,
                "error": result.error or "Calendar sync failed.",
            },
            status=502,
        )

    # Opportunistic channel renewal: a cheap DB check that only calls Google
    # when the channel is near expiry or missing. Runs after sync so it does
    # not delay the JSON response on the happy path.
    ensure_watch_channel(request.user, "primary")

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


@csrf_exempt  # Google cannot include a Django CSRF token.
@require_POST
def webhook(request):
    """Accept and process a Google Calendar push notification.

    Required headers identify the channel and notification type. Initial ``sync``
    notices are acknowledged, while ``exists`` notices require a valid shared token
    and trigger incremental synchronization. Processing failures are logged but
    acknowledged so Google does not repeatedly send the same notice.
    """
    channel_id = request.headers.get("X-Goog-Channel-ID", "")
    resource_id = request.headers.get("X-Goog-Resource-ID", "")
    resource_state = request.headers.get("X-Goog-Resource-State", "")
    token = request.headers.get("X-Goog-Channel-Token", "")
    message_number = request.headers.get("X-Goog-Message-Number", "")
    
    logger.info(
        f"Webhook received: channel={channel_id}, state={resource_state}, "
        f"message={message_number}"
    )
    
    if not channel_id or not resource_state:
        logger.warning("Webhook missing required headers")
        return HttpResponse("Missing required headers", status=400)
    
    # The first notification only confirms that the channel exists.
    if resource_state == "sync":
        logger.info(f"Received sync notification for channel {channel_id}")
        return HttpResponse("OK", status=200)
    
    if not verify_notification_token(channel_id, token):
        logger.warning(f"Token verification failed for channel {channel_id}")
        return HttpResponse("Invalid token", status=403)
    
    if resource_state == "exists":
        result = handle_push_notification(channel_id, resource_id)
        
        if result.success:
            logger.info(
                f"Push sync complete: +{result.created} ~{result.updated} "
                f"-{result.deleted}"
            )
        else:
            # A later notification or manual request can retrieve missed changes.
            logger.error(f"Push sync failed: {result.error}")

    return HttpResponse("OK", status=200)
