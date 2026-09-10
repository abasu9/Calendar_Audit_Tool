"""Copy Google Calendar changes into the local event database.

A full sync rebuilds the recent audit window and saves a Google sync token. Later
syncs use that token to request only changed events. Webhook notifications and
manual dashboard requests both enter the same incremental path.

Every public function accepts a *user* argument so data from different accounts
never mixes.
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
from .models import CalendarEvent, EventAttendee, SyncState, WatchChannel

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Describe the outcome of one calendar synchronization.

    The object tells callers whether the operation succeeded, which sync type ran,
    how many rows changed, the final event count, and any readable error message.
    """
    success: bool
    full_sync: bool
    created: int = 0
    updated: int = 0
    deleted: int = 0
    total_events: int = 0
    error: Optional[str] = None


def _sync_attendees(event_obj: CalendarEvent, event_data: dict, user) -> None:
    """Replace the attendee rows for *event_obj* with those in *event_data*.

    Delete-and-reinsert is simpler than diffing and is correct because an
    event's attendee list can change between syncs. Must be called inside an
    existing ``transaction.atomic()`` block.
    """
    EventAttendee.objects.filter(event=event_obj).delete()
    rows = []
    for attendee in (event_data.get("attendees") or []):
        email = attendee.get("email", "")
        if not email:
            continue
        rows.append(EventAttendee(
            event=event_obj,
            user=user,
            email=email,
            display_name=attendee.get("displayName", ""),
            response_status=attendee.get("responseStatus", ""),
            is_self=bool(attendee.get("self", False)),
        ))
    if rows:
        EventAttendee.objects.bulk_create(rows)


def full_sync(user, calendar_id: str = "primary") -> SyncResult:
    """Rebuild one calendar's local three-month audit window for *user*.

    Every API page from 90 days ago through now is fetched. Within one database
    transaction, events are inserted or updated, missing rows are deleted, and a
    fresh sync token is saved for future incremental requests.
    """
    logger.info("Starting full sync for user=%s calendar=%s", user, calendar_id)

    try:
        service = build_service(user=user)
    except Exception as exc:
        logger.error("Failed to build Google Calendar service: %s", exc)
        return SyncResult(success=False, full_sync=True, error=str(exc))

    # Audit reports cover the previous 90 days and exclude future events.
    now = datetime.now(tz=ZoneInfo("UTC"))
    time_min = now - timedelta(days=90)
    time_max = now  # Only past events, not future

    try:
        all_events = []
        page_token = None

        while True:
            response = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    maxResults=250,
                    pageToken=page_token,
                )
                .execute()
            )

            items = response.get("items", [])
            all_events.extend(items)
            logger.debug("Fetched %d events (total: %d)", len(items), len(all_events))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        # Google provides a reusable sync token only on an unbounded event listing.
        sync_token = _get_initial_sync_token(service, calendar_id)

        # Apply all related row and state changes together.
        with transaction.atomic():
            created = 0
            updated = 0

            existing_ids = set(
                CalendarEvent.objects.filter(user=user, calendar_id=calendar_id)
                .values_list("google_event_id", flat=True)
            )
            fetched_ids = set()

            for event_data in all_events:
                event_id = event_data["id"]
                fetched_ids.add(event_id)

                # Cancelled items should not be stored as active audit events.
                if event_data.get("status") == "cancelled":
                    continue

                defaults = CalendarEvent.parse_google_event(event_data, calendar_id)

                event_obj, was_created = CalendarEvent.objects.update_or_create(
                    user=user,
                    google_event_id=event_id,
                    defaults=defaults,
                )
                _sync_attendees(event_obj, event_data, user)

                if was_created:
                    created += 1
                else:
                    updated += 1

            # Remove rows deleted by Google or moved outside the audit window.
            ids_to_delete = existing_ids - fetched_ids
            deleted = CalendarEvent.objects.filter(
                user=user,
                google_event_id__in=ids_to_delete,
            ).delete()[0]

            SyncState.objects.update_or_create(
                user=user,
                calendar_id=calendar_id,
                defaults={
                    "sync_token": sync_token,
                    "last_full_sync": timezone.now(),
                },
            )

        total = CalendarEvent.objects.filter(user=user, calendar_id=calendar_id).count()

        logger.info(
            "Full sync complete for user=%s: %d created, %d updated, %d deleted, %d total",
            user,
            created,
            updated,
            deleted,
            total,
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
        logger.error("Google API error during full sync: %s", exc)
        return SyncResult(success=False, full_sync=True, error=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during full sync: %s", exc)
        return SyncResult(success=False, full_sync=True, error=str(exc))


def _get_initial_sync_token(service, calendar_id: str) -> str:
    """Request the token needed to begin incremental synchronization.

    Google returns ``nextSyncToken`` only after an unbounded listing reaches its
    final page, so this helper follows all page tokens and returns the final value.
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
            sync_token = response.get("nextSyncToken", "")
            break

    return sync_token


def incremental_sync(user, calendar_id: str = "primary") -> SyncResult:
    """Apply only the changes made since the last successful sync for *user*.

    The saved Google token is used across every response page. Cancelled events
    are deleted, past events are inserted or updated, and the replacement token
    is saved atomically. A missing or expired token triggers a full sync.
    """
    logger.info("Starting incremental sync for user=%s calendar=%s", user, calendar_id)

    try:
        sync_state = SyncState.objects.get(user=user, calendar_id=calendar_id)
    except SyncState.DoesNotExist:
        logger.info("No sync state found for user=%s, falling back to full sync", user)
        return full_sync(user, calendar_id)

    if not sync_state.sync_token:
        logger.info("No sync token for user=%s, falling back to full sync", user)
        return full_sync(user, calendar_id)

    try:
        service = build_service(user=user)
    except Exception as exc:
        logger.error("Failed to build Google Calendar service: %s", exc)
        return SyncResult(success=False, full_sync=False, error=str(exc))

    try:
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
                    # Google requires a new full baseline after token expiration.
                    logger.warning(
                        "Sync token expired (410 Gone) for user=%s, falling back to full sync",
                        user,
                    )
                    return full_sync(user, calendar_id)
                raise

            items = response.get("items", [])
            all_changes.extend(items)

            page_token = response.get("nextPageToken")
            if not page_token:
                new_sync_token = response.get("nextSyncToken", "")
                break

        logger.info("Received %d changes from Google for user=%s", len(all_changes), user)

        # Save event changes and the replacement token as one unit.
        with transaction.atomic():
            created = 0
            updated = 0
            deleted = 0

            existing_ids = set(
                CalendarEvent.objects.filter(user=user, calendar_id=calendar_id)
                .values_list("google_event_id", flat=True)
            )

            now = datetime.now(tz=ZoneInfo("UTC"))

            for event_data in all_changes:
                event_id = event_data["id"]

                if event_data.get("status") == "cancelled":
                    result = CalendarEvent.objects.filter(
                        user=user,
                        google_event_id=event_id,
                    ).delete()
                    if result[0] > 0:
                        deleted += 1
                        logger.debug("Deleted event: %s", event_id)
                else:
                    defaults = CalendarEvent.parse_google_event(event_data, calendar_id)

                    # Future meetings do not belong in the audit window yet.
                    if defaults["start_time"] > now:
                        logger.debug("Skipping future event: %s", event_id)
                        continue

                    event_obj, was_created = CalendarEvent.objects.update_or_create(
                        user=user,
                        google_event_id=event_id,
                        defaults=defaults,
                    )
                    _sync_attendees(event_obj, event_data, user)

                    if was_created:
                        created += 1
                        logger.debug("Created event: %s", event_id)
                    else:
                        updated += 1
                        logger.debug("Updated event: %s", event_id)

            sync_state.sync_token = new_sync_token
            sync_state.save()

        total = CalendarEvent.objects.filter(user=user, calendar_id=calendar_id).count()

        logger.info(
            "Incremental sync complete for user=%s: %d created, %d updated, %d deleted, %d total",
            user,
            created,
            updated,
            deleted,
            total,
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
        logger.error("Google API error during incremental sync: %s", exc)
        return SyncResult(success=False, full_sync=False, error=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during incremental sync: %s", exc)
        return SyncResult(success=False, full_sync=False, error=str(exc))


def handle_push_notification(channel_id: str, resource_id: str) -> SyncResult:
    """Validate a Google change notice and synchronize its calendar.

    Webhook requests contain channel identifiers but no event details. This helper
    finds an active, unexpired subscription, resolves the owning user from the
    channel record, and then runs the incremental sync that retrieves the actual
    changes.
    """
    logger.info("Handling push notification: channel=%s", channel_id)

    try:
        channel = WatchChannel.objects.select_related("user").get(
            channel_id=channel_id, active=True
        )
    except WatchChannel.DoesNotExist:
        logger.warning("Push notification for unknown/inactive channel: %s", channel_id)
        return SyncResult(
            success=False,
            full_sync=False,
            error=f"Unknown or inactive channel: {channel_id}",
        )

    # Keep the mismatch visible; Google may occasionally change this identifier.
    if channel.resource_id and channel.resource_id != resource_id:
        logger.warning(
            "Resource ID mismatch: expected %s, got %s",
            channel.resource_id,
            resource_id,
        )

    if channel.is_expired:
        logger.warning("Push notification for expired channel: %s", channel_id)
        channel.active = False
        channel.save()
        return SyncResult(success=False, full_sync=False, error="Channel has expired")

    return incremental_sync(channel.user, channel.calendar_id)
