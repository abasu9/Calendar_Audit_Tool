"""
Django Management Command: stop_watch

PURPOSE:
Stop a watch channel (unsubscribe from push notifications).
Use this to clean up channels you no longer need.

USAGE:
    # Stop a specific channel by ID
    python manage.py stop_watch --channel-id abc123-def456-...
    
    # List active channels without stopping
    python manage.py stop_watch --list
    
    # Stop ALL active channels (use with caution)
    python manage.py stop_watch --all

WHEN TO USE:
- When you're done testing push notifications
- When switching webhook URLs
- When a channel is about to expire and you're creating a new one
"""

from django.core.management.base import BaseCommand, CommandError

from calsync.watch import (
    cleanup_expired_channels,
    get_active_channels,
    stop_watch_channel,
)


class Command(BaseCommand):
    """
    Stop a watch channel or list active channels.
    """
    
    help = "Stop a watch channel for Google Calendar push notifications."
    
    def add_arguments(self, parser):
        """
        Define command-line arguments.
        
        ARGUMENTS:
        --channel-id : Specific channel UUID to stop
        --list       : Just list active channels, don't stop anything
        --all        : Stop ALL active channels
        """
        parser.add_argument(
            "--channel-id",
            type=str,
            help="Channel ID (UUID) to stop.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List active channels without stopping.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Stop ALL active channels.",
        )
    
    def handle(self, *args, **options):
        """
        Main entry point - stop channel(s) or list them.
        """
        # Clean up any expired channels first
        expired_count = cleanup_expired_channels()
        if expired_count > 0:
            self.stdout.write(
                f"Cleaned up {expired_count} expired channel(s)."
            )
        
        # Get all active channels
        active_channels = get_active_channels()
        
        if options["list"]:
            # Just list channels
            self._list_channels(active_channels)
            return
        
        if options["all"]:
            # Stop all channels
            self._stop_all_channels(active_channels)
            return
        
        if options["channel_id"]:
            # Stop specific channel
            self._stop_channel(options["channel_id"])
            return
        
        # No action specified - show help
        self._list_channels(active_channels)
        self.stdout.write(
            "\nUse --channel-id UUID to stop a specific channel, "
            "or --all to stop all."
        )
    
    def _list_channels(self, channels):
        """
        Display all active channels.
        """
        if not channels:
            self.stdout.write("No active watch channels.")
            return
        
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\nActive watch channels ({len(channels)}):")
        )
        
        for ch in channels:
            self.stdout.write(f"\n  Channel ID: {ch.channel_id}")
            self.stdout.write(f"  Calendar: {ch.calendar_id}")
            self.stdout.write(f"  Webhook: {ch.webhook_url}")
            self.stdout.write(f"  Expires: {ch.expiration.isoformat()}")
            if ch.is_expired:
                self.stdout.write(self.style.WARNING("  Status: EXPIRED"))
    
    def _stop_channel(self, channel_id):
        """
        Stop a specific channel.
        """
        self.stdout.write(f"Stopping channel: {channel_id}")
        
        success = stop_watch_channel(channel_id)
        
        if success:
            self.stdout.write(
                self.style.SUCCESS("Channel stopped successfully.")
            )
        else:
            raise CommandError(
                "Failed to stop channel. It may not exist or already be stopped."
            )
    
    def _stop_all_channels(self, channels):
        """
        Stop all active channels.
        """
        if not channels:
            self.stdout.write("No active channels to stop.")
            return
        
        self.stdout.write(
            self.style.WARNING(f"Stopping {len(channels)} channel(s)...")
        )
        
        success_count = 0
        for ch in channels:
            if stop_watch_channel(str(ch.channel_id)):
                self.stdout.write(f"  Stopped: {ch.channel_id}")
                success_count += 1
            else:
                self.stdout.write(
                    self.style.ERROR(f"  Failed: {ch.channel_id}")
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nStopped {success_count}/{len(channels)} channel(s)."
            )
        )
