"""Bootstrap calendar data after a new OAuth connection.

After a user authorises via Google OAuth, the application needs to populate its
local event database and register a push-notification channel. Both operations
run in a background daemon thread so the OAuth callback returns immediately.

The module-level lock and in-flight flag prevent duplicate imports if the
callback fires twice or the dashboard view triggers a retry while one is already
running.
"""

import logging
import threading

from django.db import connections

logger = logging.getLogger(__name__)

_bootstrap_lock = threading.Lock()
_bootstrap_in_flight = False


def bootstrap_calendar(calendar_id: str = "primary") -> None:
    """Run a full sync then ensure a push channel exists for one calendar.

    Called from a background thread. Both operations are best-effort: a sync
    failure leaves no SyncState row, so the existing manual-sync button will
    retry via incremental_sync() which falls back to full_sync() automatically.
    A channel failure is logged but does not prevent the import from completing.
    """
    # Import here to avoid circular imports (sync imports models, models import nothing).
    from calsync.sync import full_sync
    from calsync.watch import ensure_watch_channel

    logger.info("Bootstrap started for calendar: %s", calendar_id)

    try:
        result = full_sync(calendar_id)
        if result.success:
            logger.info(
                "Bootstrap sync complete: %d created, %d updated, %d deleted, %d total",
                result.created,
                result.updated,
                result.deleted,
                result.total_events,
            )
        else:
            logger.error("Bootstrap sync failed: %s", result.error)
    except Exception:
        logger.exception("Unexpected error during bootstrap sync")

    try:
        ensure_watch_channel(calendar_id)
    except Exception:
        logger.exception("Unexpected error during bootstrap watch-channel setup")

    logger.info("Bootstrap finished for calendar: %s", calendar_id)


def start_bootstrap(calendar_id: str = "primary") -> bool:
    """Start bootstrap_calendar() in a background daemon thread.

    Returns True when the thread is launched, False when one is already running.
    The thread closes all database connections before it exits so no pooled
    Supabase connections are left open.
    """
    global _bootstrap_in_flight

    with _bootstrap_lock:
        if _bootstrap_in_flight:
            logger.info(
                "Bootstrap already in progress for %s, skipping duplicate start",
                calendar_id,
            )
            return False
        _bootstrap_in_flight = True

    def _run():
        global _bootstrap_in_flight
        try:
            bootstrap_calendar(calendar_id)
        finally:
            connections.close_all()
            with _bootstrap_lock:
                _bootstrap_in_flight = False

    thread = threading.Thread(target=_run, daemon=True, name="calendar-bootstrap")
    thread.start()
    logger.info("Bootstrap thread started for calendar: %s", calendar_id)
    return True
