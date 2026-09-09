"""List or stop Google Calendar webhook subscriptions.

The command reads saved active channels and can deactivate one channel or all of
them both at Google and in the local database.
"""

from django.core.management.base import BaseCommand, CommandError

from calsync.watch import (
    cleanup_expired_channels,
    get_active_channels,
    stop_watch_channel,
)


class Command(BaseCommand):
    """Expose watch-channel inspection and cleanup as a Django command."""
    
    help = "Stop a watch channel for Google Calendar push notifications."
    
    def add_arguments(self, parser):
        """Register options for listing, stopping one, or stopping all channels.

        Django parses these mutually meaningful actions and supplies their values
        to ``handle``.
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
        """Clean expired records and run the action selected by the user.

        The function checks list, all, and channel-ID options in order. With no
        action it prints the active channels and a short usage hint.
        """
        expired_count = cleanup_expired_channels()
        if expired_count > 0:
            self.stdout.write(
                f"Cleaned up {expired_count} expired channel(s)."
            )
        
        active_channels = get_active_channels()
        
        if options["list"]:
            self._list_channels(active_channels)
            return
        
        if options["all"]:
            self._stop_all_channels(active_channels)
            return
        
        if options["channel_id"]:
            self._stop_channel(options["channel_id"])
            return
        
        self._list_channels(active_channels)
        self.stdout.write(
            "\nUse --channel-id UUID to stop a specific channel, "
            "or --all to stop all."
        )
    
    def _list_channels(self, channels):
        """Print the important fields for each active channel.

        An empty collection produces a clear message; otherwise every channel is
        listed with its calendar, callback URL, expiration, and expired state.
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
        """Stop one channel and turn a failed stop into a command error.

        The shared watch helper contacts Google and updates the database, while
        this method only formats the command-line result.
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
        """Try to stop every supplied channel and print a final count.

        Each channel is handled independently so one failure does not prevent the
        command from cleaning up the remaining subscriptions.
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
