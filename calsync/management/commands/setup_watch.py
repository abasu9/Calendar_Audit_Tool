"""Create a Google Calendar webhook subscription from the command line.

The command accepts a public callback URL, calendar, and lifetime, then asks
Google to send change notifications to that URL. Local development needs a
public HTTPS tunnel because Google cannot call a localhost address.
"""

from django.core.management.base import BaseCommand, CommandError

from calsync.watch import create_watch_channel, get_active_channels


class Command(BaseCommand):
    """Expose watch-channel creation as a Django management command."""
    
    help = "Set up a watch channel for Google Calendar push notifications."
    
    def add_arguments(self, parser):
        """Register the webhook URL, calendar ID, and lifetime options.

        Django uses these definitions to validate command-line input and provide
        defaults before passing the values to ``handle``.
        """
        parser.add_argument(
            "--url",
            type=str,
            required=True,
            help="Webhook URL (must be HTTPS with valid certificate).",
        )
        parser.add_argument(
            "--calendar",
            type=str,
            default="primary",
            help="Calendar ID to watch (default: primary).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Channel expiration in days (default: 7).",
        )
    
    def handle(self, *args, **options):
        """Create the requested channel and print its saved details.

        Existing channels are shown first to make duplicates visible. The command
        then calls Google through ``create_watch_channel`` and reports a useful
        error when registration fails.
        """
        webhook_url = options["url"]
        calendar_id = options["calendar"]
        expiration_days = options["days"]
        
        # Public Google callbacks normally require HTTPS.
        if webhook_url.startswith("http://") and "localhost" not in webhook_url:
            self.stdout.write(
                self.style.WARNING(
                    "WARNING: Non-HTTPS URLs may be rejected by Google "
                    "(except localhost for testing)."
                )
            )
        
        # Make existing subscriptions visible before adding another one.
        active_channels = get_active_channels(calendar_id)
        if active_channels:
            self.stdout.write(f"\nExisting active channels for {calendar_id}:")
            for ch in active_channels:
                self.stdout.write(
                    f"  - {ch.channel_id} expires {ch.expiration.isoformat()}"
                )
            self.stdout.write("")
        
        self.stdout.write(f"Creating watch channel...")
        self.stdout.write(f"  Calendar: {calendar_id}")
        self.stdout.write(f"  Webhook URL: {webhook_url}")
        self.stdout.write(f"  Expiration: {expiration_days} days")
        
        channel = create_watch_channel(
            calendar_id=calendar_id,
            webhook_url=webhook_url,
            expiration_days=expiration_days,
        )
        
        if not channel:
            raise CommandError(
                "Failed to create watch channel. Check the logs for details.\n"
                "Common issues:\n"
                "  - URL must be HTTPS with valid certificate\n"
                "  - Google cannot reach localhost directly\n"
                "  - Use ngrok for local development"
            )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nWatch channel created successfully!"
            )
        )
        self.stdout.write(f"  Channel ID: {channel.channel_id}")
        self.stdout.write(f"  Resource ID: {channel.resource_id}")
        self.stdout.write(f"  Token: {channel.token}")
        self.stdout.write(f"  Expires: {channel.expiration.isoformat()}")
        
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "\nTo test with the mock script, copy these values to simulate_push.py"
            )
        )
        self.stdout.write(
            f"    CHANNEL_ID = \"{channel.channel_id}\"\n"
            f"    RESOURCE_ID = \"{channel.resource_id}\"\n"
            f"    TOKEN = \"{channel.token}\""
        )
