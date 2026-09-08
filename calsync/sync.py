"""
Calendar Sync Engine

PURPOSE:
Handles synchronization between Google Calendar and our local database.
Supports both full sync (fetch everything) and incremental sync (only changes).

HOW IT WORKS:

FULL SYNC:
1. Clear any existing sync token (start fresh)
2. Fetch ALL events from Google Calendar (with pagination)
3. Upsert each event into our CalendarEvent table
4. Store the syncToken Google returns for future incremental syncs

INCREMENTAL SYNC:
1. Load the syncToken from our last sync
2. Call events.list(syncToken=token) - Google only returns changes
3. For each changed event:
   - If status="cancelled": delete from our database
   - Otherwise: upsert (create or update)
4. Store the new syncToken

WHY INCREMENTAL?
- Much faster (only fetches changes, not everything)
- Uses less API quota
- Combined with push notifications, enables near-instant updates

SYNC TOKEN EXPIRATION:
Google's syncToken can expire (returns HTTP 410 Gone). When this happens,
we automatically fall back to a full sync.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from googleapiclient.errors import HttpError

from googlecal.client import build_service
from .models import CalendarEvent, SyncState, WatchChannel

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """
    Result of a sync operation.
    
    FIELDS:
    - success: Whether the sync completed without errors
    - full_sync: Whether this was a full sync (vs incremental)
    - created: Number of new events added
    - updated: Number of existing events updated
    - deleted: Number of events removed
    - total_events: Total events in database after sync
    - error: Error message if sync failed
    """
    success: bool
    full_sync: bool
    created: int = 0
    updated: int = 0
    deleted: int = 0
    total_events: int = 0
    error: Optional[str] = None


def full_sync(calendar_id: str = "primary") -> SyncResult:
    """
    Perform a full synchronization - fetch ALL events from Google Calendar.
    
    WHEN TO USE:
    - Initial sync (no syncToken exists yet)
    - After syncToken expires (Google returns 410 Gone)
    - When you want to ensure 100% consistency with Google
    
    PARAMETERS:
    - calendar_id: Which calendar to sync (default "primary")
    
    RETURNS:
    - SyncResult with counts of created/updated events
    
    WHAT THIS DOES:
    1. Clear any existing sync token for this calendar
    2. Fetch all events in a wide time window (past 3 months to future 1 year)
    3. Delete events no longer in Google (not in the fetched set)
    4. Upsert all fetched events
    5. Save the new sync token
    """
    logger.info(f"Starting full sync for calendar: {calendar_id}")
    
    try:
        service = build_service()
    except Exception as exc:
        logger.error(f"Failed to build Google Calendar service: {exc}")
        return SyncResult(success=False, full_sync=True, error=str(exc))
    
    # Time window: past 3 months up to NOW (audit is for past events only)
    # This covers the audit requirement (3 months history)
    now = datetime.now(tz=ZoneInfo("UTC"))
    time_min = now - timedelta(days=90)
    time_max = now  # Only past events, not future
    
    try:
        # Fetch all events with pagination
        all_events = []
        page_token = None
        
        while True:
            response = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,  # Expand recurring events
                    maxResults=250,
                    pageToken=page_token,
                )
                .execute()
            )
            
            items = response.get("items", [])
            all_events.extend(items)
            logger.debug(f"Fetched {len(items)} events (total: {len(all_events)})")
            
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        
        # Get the sync token for future incremental syncs
        # Note: For full sync, we need to do one more call without time bounds
        # to get a proper syncToken
        sync_token = _get_initial_sync_token(service, calendar_id)
        
        # Process events in a transaction
        with transaction.atomic():
            created = 0
            updated = 0
            
            # Get existing event IDs for this calendar
            existing_ids = set(
                CalendarEvent.objects.filter(calendar_id=calendar_id)
                .values_list("google_event_id", flat=True)
            )
            fetched_ids = set()
            
            for event_data in all_events:
                event_id = event_data["id"]
                fetched_ids.add(event_id)
                
                # Skip cancelled events (they shouldn't appear in full sync, but just in case)
                if event_data.get("status") == "cancelled":
                    continue
                
                # Parse event data into field values
                defaults = CalendarEvent.parse_google_event(event_data, calendar_id)
                
                # Use update_or_create to properly handle created_at/updated_at
                _, was_created = CalendarEvent.objects.update_or_create(
                    google_event_id=event_id,
                    defaults=defaults,
                )
                
                if was_created:
                    created += 1
                else:
                    updated += 1
            
            # Delete events that are no longer in Google
            # (They were deleted or moved outside our time window)
            ids_to_delete = existing_ids - fetched_ids
            deleted = CalendarEvent.objects.filter(
                google_event_id__in=ids_to_delete
            ).delete()[0]
            
            # Save sync state
            SyncState.objects.update_or_create(
                calendar_id=calendar_id,
                defaults={
                    "sync_token": sync_token,
                    "last_full_sync": timezone.now(),
                }
            )
        
        total = CalendarEvent.objects.filter(calendar_id=calendar_id).count()
        
        logger.info(
            f"Full sync complete: {created} created, {updated} updated, "
            f"{deleted} deleted, {total} total"
        )
        
        return SyncResult(
            success=True,
            full_sync=True,
            created=created,
            updated=updated,
            deleted=deleted,
            total_events=total,
        )
        
    except HttpError as exc:
        logger.error(f"Google API error during full sync: {exc}")
        return SyncResult(success=False, full_sync=True, error=str(exc))
    except Exception as exc:
        logger.exception(f"Unexpected error during full sync: {exc}")
        return SyncResult(success=False, full_sync=True, error=str(exc))


def _get_initial_sync_token(service, calendar_id: str) -> str:
    """
    Get an initial sync token for incremental syncs.
    
    To get a syncToken, we need to list events WITHOUT time bounds and
    iterate through ALL pages. The token is in the last page's response.
    
    This is expensive, so we only do it during full sync.
    """
    page_token = None
    sync_token = ""
    
    while True:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                maxResults=250,
                pageToken=page_token,
            )
            .execute()
        )
        
        page_token = response.get("nextPageToken")
        if not page_token:
            # Last page - get the sync token
            sync_token = response.get("nextSyncToken", "")
            break
    
    return sync_token


def incremental_sync(calendar_id: str = "primary") -> SyncResult:
    """
    Perform an incremental sync - fetch only changes since last sync.
    
    WHEN TO USE:
    - After a push notification indicates changes
    - As a periodic check for missed notifications
    - Any time after the initial full sync
    
    PARAMETERS:
    - calendar_id: Which calendar to sync (default "primary")
    
    RETURNS:
    - SyncResult with counts of created/updated/deleted events
    
    WHAT THIS DOES:
    1. Load the syncToken from our last sync
    2. If no token, fall back to full_sync()
    3. Call events.list(syncToken=token)
    4. Process each change:
       - status="cancelled" -> delete
       - otherwise -> upsert
    5. Save the new syncToken
    
    SYNC TOKEN EXPIRATION:
    If Google returns 410 Gone, the token expired and we do a full sync.
    """
    logger.info(f"Starting incremental sync for calendar: {calendar_id}")
    
    # Load existing sync state
    try:
        sync_state = SyncState.objects.get(calendar_id=calendar_id)
    except SyncState.DoesNotExist:
        logger.info("No sync state found, falling back to full sync")
        return full_sync(calendar_id)
    
    if not sync_state.sync_token:
        logger.info("No sync token found, falling back to full sync")
        return full_sync(calendar_id)
    
    try:
        service = build_service()
    except Exception as exc:
        logger.error(f"Failed to build Google Calendar service: {exc}")
        return SyncResult(success=False, full_sync=False, error=str(exc))
    
    try:
        # Fetch changes since last sync
        all_changes = []
        page_token = None
        new_sync_token = ""
        
        while True:
            try:
                response = (
                    service.events()
                    .list(
                        calendarId=calendar_id,
                        syncToken=sync_state.sync_token,
                        maxResults=250,
                        pageToken=page_token,
                    )
                    .execute()
                )
            except HttpError as exc:
                if exc.resp.status == 410:
                    # Sync token expired - need full sync
                    logger.warning("Sync token expired (410 Gone), falling back to full sync")
                    return full_sync(calendar_id)
                raise
            
            items = response.get("items", [])
            all_changes.extend(items)
            
            page_token = response.get("nextPageToken")
            if not page_token:
                new_sync_token = response.get("nextSyncToken", "")
                break
        
        logger.info(f"Received {len(all_changes)} changes from Google")
        
        # Process changes in a transaction
        with transaction.atomic():
            created = 0
            updated = 0
            deleted = 0
            
            # Get existing event IDs
            existing_ids = set(
                CalendarEvent.objects.filter(calendar_id=calendar_id)
                .values_list("google_event_id", flat=True)
            )
            
            now = datetime.now(tz=ZoneInfo("UTC"))
            
            for event_data in all_changes:
                event_id = event_data["id"]
                
                if event_data.get("status") == "cancelled":
                    # Event was deleted or declined
                    result = CalendarEvent.objects.filter(
                        google_event_id=event_id
                    ).delete()
                    if result[0] > 0:
                        deleted += 1
                        logger.debug(f"Deleted event: {event_id}")
                else:
                    # Event was created or updated
                    # Parse event data into field values
                    defaults = CalendarEvent.parse_google_event(event_data, calendar_id)
                    
                    # Skip future events - audit is for past events only
                    if defaults["start_time"] > now:
                        logger.debug(f"Skipping future event: {event_id}")
                        continue
                    
                    # Use update_or_create to properly handle created_at/updated_at
                    _, was_created = CalendarEvent.objects.update_or_create(
                        google_event_id=event_id,
                        defaults=defaults,
                    )
                    
                    if was_created:
                        created += 1
                        logger.debug(f"Created event: {event_id}")
                    else:
                        updated += 1
                        logger.debug(f"Updated event: {event_id}")
            
            # Update sync state
            sync_state.sync_token = new_sync_token
            sync_state.save()
        
        total = CalendarEvent.objects.filter(calendar_id=calendar_id).count()
        
        logger.info(
            f"Incremental sync complete: {created} created, {updated} updated, "
            f"{deleted} deleted, {total} total"
        )
        
        return SyncResult(
            success=True,
            full_sync=False,
            created=created,
            updated=updated,
            deleted=deleted,
            total_events=total,
        )
        
    except HttpError as exc:
        logger.error(f"Google API error during incremental sync: {exc}")
        return SyncResult(success=False, full_sync=False, error=str(exc))
    except Exception as exc:
        logger.exception(f"Unexpected error during incremental sync: {exc}")
        return SyncResult(success=False, full_sync=False, error=str(exc))


def handle_push_notification(channel_id: str, resource_id: str) -> SyncResult:
    """
    Handle a push notification from Google Calendar.
    
    WHAT IS A PUSH NOTIFICATION?
    When events change, Google sends a POST to our webhook with headers
    identifying which channel/resource changed. The notification contains
    NO event data - we must call the API to get the actual changes.
    
    PARAMETERS:
    - channel_id: Our UUID for the watch channel (from X-Goog-Channel-ID)
    - resource_id: Google's resource ID (from X-Goog-Resource-ID)
    
    RETURNS:
    - SyncResult from the incremental sync
    
    WHAT THIS DOES:
    1. Find the WatchChannel by channel_id
    2. Verify it's active and matches the resource_id
    3. Trigger an incremental sync for that calendar
    """
    logger.info(f"Handling push notification: channel={channel_id}")
    
    try:
        channel = WatchChannel.objects.get(channel_id=channel_id, active=True)
    except WatchChannel.DoesNotExist:
        logger.warning(f"Push notification for unknown/inactive channel: {channel_id}")
        return SyncResult(
            success=False,
            full_sync=False,
            error=f"Unknown or inactive channel: {channel_id}"
        )
    
    # Verify resource_id matches (extra security check)
    if channel.resource_id and channel.resource_id != resource_id:
        logger.warning(
            f"Resource ID mismatch: expected {channel.resource_id}, got {resource_id}"
        )
        # Don't fail - resource_id can change in some cases
    
    # Check if channel is expired
    if channel.is_expired:
        logger.warning(f"Push notification for expired channel: {channel_id}")
        channel.active = False
        channel.save()
        return SyncResult(
            success=False,
            full_sync=False,
            error="Channel has expired"
        )
    
    # Trigger incremental sync
    return incremental_sync(channel.calendar_id)
