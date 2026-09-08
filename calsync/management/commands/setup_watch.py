"""
Django Management Command: setup_watch

PURPOSE:
Create a watch channel to receive push notifications from Google Calendar.
When events change, Google will POST to your webhook URL.

USAGE:
    # Create watch channel for primary calendar
    python manage.py setup_watch --url https://your-domain.com/api/webhook/
    
    # Watch a specific calendar
    python manage.py setup_watch --url https://example.com/api/webhook/ --calendar user@example.com
    
    # Custom expiration (default: 7 days)
    python manage.py setup_watch --url https://example.com/api/webhook/ --days 14

REQUIREMENTS:
- URL must be HTTPS with a valid (non-self-signed) certificate
- Google cannot reach localhost directly
- For local development: use ngrok (ngrok http 8000) and use the HTTPS URL

FOR LOCAL TESTING WITHOUT TUNNEL:
Use the mock script instead:
    python scripts/simulate_push.py
"""

from django.core.management.base import BaseCommand, CommandError

from calsync.watch import create_watch_channel, get_active_channels


class Command(BaseCommand):
    """
    Create a watch channel for Google Calendar push notifications.
    """
    
    help = "Set up a watch channel for Google Calendar push notifications."
    
    def add_arguments(self, parser):
        """
        Define command-line arguments.
        
        ARGUMENTS:
        --url       : Webhook URL (required, must be HTTPS)
        --calendar  : Which calendar to watch (default: primary)
        --days      : Expiration in days (default: 7, max ~30)
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
        """
        Main entry point - create the watch channel.
        
        WHAT THIS DOES:
        1. Show any existing active channels
        2. Create a new watch channel via Google API
        3. Display the channel details (needed for testing)
        """
        webhook_url = options["url"]
        calendar_id = options["calendar"]
        expiration_days = options["days"]
        
        # Warn about HTTP URLs
        if webhook_url.startswith("http://") and "localhost" not in webhook_url:
            self.stdout.write(
                self.style.WARNING(
                    "WARNING: Non-HTTPS URLs may be rejected by Google "
                    "(except localhost for testing)."
                )
            )
        
        # Show existing channels
        active_channels = get_active_channels(calendar_id)
        if active_channels:
            self.stdout.write(f"\nExisting active channels for {calendar_id}:")
            for ch in active_channels:
                self.stdout.write(
                    f"  - {ch.channel_id} expires {ch.expiration.isoformat()}"
                )
            self.stdout.write("")
        
        # Create the watch channel
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
