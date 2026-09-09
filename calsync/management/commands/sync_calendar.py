"""Synchronize Google Calendar events from the command line.

The command performs a full sync when requested or when no saved token exists.
Otherwise it asks Google only for changes since the previous sync.
"""

from django.core.management.base import BaseCommand, CommandError

from calsync.models import CalendarEvent, SyncState
from calsync.sync import full_sync, incremental_sync


class Command(BaseCommand):
    """Expose full and incremental calendar synchronization as a command."""
    
    help = "Synchronize calendar events from Google Calendar."
    
    def add_arguments(self, parser):
        """Register the force-full flag and calendar ID option.

        Django validates these values and supplies defaults before calling
        ``handle``.
        """
        parser.add_argument(
            "--full",
            action="store_true",
            help="Force a full sync instead of incremental.",
        )
        parser.add_argument(
            "--calendar",
            type=str,
            default="primary",
            help="Calendar ID to sync (default: primary).",
        )
    
    def handle(self, *args, **options):
        """Choose a sync type, run it, and print event counts.

        Saved state determines whether an incremental sync is possible. A failed
        result becomes a command error; a successful result includes a short event
        preview.
        """
        calendar_id = options["calendar"]
        do_full_sync = options["full"]
        
        # A saved token allows Google to return only later changes.
        try:
            sync_state = SyncState.objects.get(calendar_id=calendar_id)
            has_token = bool(sync_state.sync_token)
            last_sync = sync_state.last_sync
            self.stdout.write(
                f"Last sync: {last_sync.isoformat() if last_sync else 'never'}"
            )
            self.stdout.write(f"Has sync token: {has_token}")
        except SyncState.DoesNotExist:
            self.stdout.write("No previous sync state found.")
            has_token = False
        
        if do_full_sync:
            self.stdout.write(self.style.WARNING("\nStarting FULL sync..."))
            result = full_sync(calendar_id)
        elif not has_token:
            self.stdout.write(
                self.style.WARNING("\nNo sync token - starting FULL sync...")
            )
            result = full_sync(calendar_id)
        else:
            self.stdout.write("\nStarting incremental sync...")
            result = incremental_sync(calendar_id)
        
        if not result.success:
            raise CommandError(f"Sync failed: {result.error}")
        
        sync_type = "Full" if result.full_sync else "Incremental"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{sync_type} sync completed successfully!"
            )
        )
        self.stdout.write(f"  Created: {result.created}")
        self.stdout.write(f"  Updated: {result.updated}")
        self.stdout.write(f"  Deleted: {result.deleted}")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"  Total events in database: {result.total_events}"
            )
        )
        
        # Keep the console preview short on calendars with many events.
        total_count = CalendarEvent.objects.filter(calendar_id=calendar_id).count()
        recent = CalendarEvent.objects.filter(
            calendar_id=calendar_id
        ).order_by("start_time")[:10]
        
        if recent:
            self.stdout.write("\nEvents:")
            for event in recent:
                self.stdout.write(
                    f"  {event.start_time.date()} - {event.summary[:50]}"
                )
            if total_count > 10:
                self.stdout.write(f"  ... and {total_count - 10} more")
