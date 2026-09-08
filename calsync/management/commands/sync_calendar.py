"""
Django Management Command: sync_calendar

PURPOSE:
Synchronize calendar events from Google Calendar to our local database.
Supports both full sync (fetch everything) and incremental sync (only changes).

USAGE:
    # Incremental sync (default - only fetch changes since last sync)
    python manage.py sync_calendar
    
    # Full sync (fetch all events, ignore existing syncToken)
    python manage.py sync_calendar --full
    
    # Sync a specific calendar (not just "primary")
    python manage.py sync_calendar --calendar user@example.com

WHEN TO USE:
- --full: First time setup, or if you suspect data is out of sync
- (no flags): Regular sync, triggered by cron or push notifications
"""

from django.core.management.base import BaseCommand, CommandError

from calsync.models import CalendarEvent, SyncState
from calsync.sync import full_sync, incremental_sync


class Command(BaseCommand):
    """
    Sync calendar events from Google Calendar to local database.
    """
    
    help = "Synchronize calendar events from Google Calendar."
    
    def add_arguments(self, parser):
        """
        Define command-line arguments.
        
        ARGUMENTS:
        --full      : Force full sync (ignore existing syncToken)
        --calendar  : Which calendar to sync (default: primary)
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
        """
        Main entry point - run the sync.
        
        WHAT THIS DOES:
        1. Check if full or incremental sync
        2. Call appropriate sync function
        3. Print results
        """
        calendar_id = options["calendar"]
        do_full_sync = options["full"]
        
        # Show current state
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
        
        # Determine sync type
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
        
        # Show results
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
        
        # Show recent events (all if <= 10, otherwise first 10)
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
