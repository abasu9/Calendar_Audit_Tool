"""Bootstrap calendar data after a new OAuth connection.

After a user authorises via Google OAuth, the application needs to populate its
local event database and register a push-notification channel. Both operations
run in a background daemon thread so the OAuth callback returns immediately.

A module-level lock and set of in-flight ``(user_id, calendar_id)`` pairs prevent
duplicate bootstrap runs for the same user. The thread re-fetches the User object
by primary key so it does not hold a cross-thread ORM reference, and closes all
database connections before it exits to avoid leaking pooled Supabase connections.
"""

import logging
import threading

from django.db import connections

logger = logging.getLogger(__name__)

_bootstrap_lock = threading.Lock()
# Set of (user_id, calendar_id) tuples currently bootstrapping.
_in_flight: set = set()


def bootstrap_calendar(user_id: int, calendar_id: str = "primary") -> None:
    """Run a full sync then ensure a push channel exists for *user_id*'s calendar.

    Called from a background thread. Both operations are best-effort: a sync
    failure leaves no SyncState row, so the manual-sync button will retry via
    incremental_sync() which falls back to full_sync() automatically. A channel
    failure is logged but does not prevent the sync from completing.
    """
    from django.contrib.auth import get_user_model
    from calsync.sync import full_sync
    from calsync.watch import ensure_watch_channel

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("Bootstrap: user %s not found, aborting", user_id)
        return

    logger.info("Bootstrap started for user=%s calendar=%s", user, calendar_id)

    try:
        result = full_sync(user, calendar_id)
        if result.success:
            logger.info(
                "Bootstrap sync complete for user=%s: %d created, %d updated, "
                "%d deleted, %d total",
                user,
                result.created,
                result.updated,
                result.deleted,
                result.total_events,
            )
        else:
            logger.error("Bootstrap sync failed for user=%s: %s", user, result.error)
    except Exception:
        logger.exception("Unexpected error during bootstrap sync for user=%s", user)

    try:
        ensure_watch_channel(user, calendar_id)
    except Exception:
        logger.exception(
            "Unexpected error during bootstrap watch-channel setup for user=%s", user
        )

    logger.info("Bootstrap finished for user=%s calendar=%s", user, calendar_id)


def start_bootstrap(user_id: int, calendar_id: str = "primary") -> bool:
    """Start bootstrap_calendar() in a background daemon thread.

    Returns True when the thread is launched, False when one is already running
    for the same (user_id, calendar_id) pair. The thread closes all database
    connections before it exits so no pooled Supabase connections are left open.
    """
    key = (user_id, calendar_id)

    with _bootstrap_lock:
        if key in _in_flight:
            logger.info(
                "Bootstrap already in progress for user=%s calendar=%s, skipping",
                user_id,
                calendar_id,
            )
            return False
        _in_flight.add(key)

    def _run():
        try:
            bootstrap_calendar(user_id, calendar_id)
        finally:
            connections.close_all()
            with _bootstrap_lock:
                _in_flight.discard(key)

    thread = threading.Thread(
        target=_run,
        daemon=True,
        name=f"calendar-bootstrap-{user_id}-{calendar_id}",
    )
    thread.start()
    logger.info(
        "Bootstrap thread started for user=%s calendar=%s", user_id, calendar_id
    )
    return True
