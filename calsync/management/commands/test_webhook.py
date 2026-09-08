"""
Django Management Command: test_webhook

PURPOSE:
Test the webhook endpoint by simulating a Google push notification.
Uses an existing WatchChannel record from the database, so you don't
have to manually copy tokens around.

USAGE:
    # Test with the first active watch channel
    python manage.py test_webhook
    
    # Test with a specific channel
    python manage.py test_webhook --channel-id abc123-...
    
    # Simulate a sync message (initial notification)
    python manage.py test_webhook --sync

PREREQUISITES:
1. Server must be running: python manage.py runserver
2. At least one WatchChannel must exist (create with setup_watch or Django shell)
"""

import requests
from django.core.management.base import BaseCommand, CommandError

from calsync.models import WatchChannel


class Command(BaseCommand):
    """
    Test the webhook endpoint with a simulated push notification.
    """
    
    help = "Test the webhook endpoint with a simulated Google push notification."
    
    def add_arguments(self, parser):
        parser.add_argument(
            "--channel-id",
            type=str,
            help="Specific channel ID to use (default: first active channel).",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Send a 'sync' message instead of 'exists'.",
        )
        parser.add_argument(
            "--url",
            type=str,
            default="http://localhost:8000/api/webhook/",
            help="Webhook URL to test (default: localhost:8000).",
        )
    
    def handle(self, *args, **options):
        # Find a watch channel to use
        if options["channel_id"]:
            try:
                channel = WatchChannel.objects.get(channel_id=options["channel_id"])
            except WatchChannel.DoesNotExist:
                raise CommandError(f"Channel not found: {options['channel_id']}")
        else:
            channel = WatchChannel.objects.filter(active=True).first()
            if not channel:
                raise CommandError(
                    "No active watch channels found. "
                    "Create one with: python manage.py setup_watch --url ..."
                )
        
        state = "sync" if options["sync"] else "exists"
        webhook_url = options["url"]
        
        self.stdout.write(f"Testing webhook endpoint...")
        self.stdout.write(f"  URL: {webhook_url}")
        self.stdout.write(f"  Channel ID: {channel.channel_id}")
        self.stdout.write(f"  Resource State: {state}")
        
        # Build headers exactly like Google would
        headers = {
            "X-Goog-Channel-ID": str(channel.channel_id),
            "X-Goog-Resource-ID": channel.resource_id or "mock-resource",
            "X-Goog-Resource-State": state,
            "X-Goog-Channel-Token": channel.token,
            "X-Goog-Message-Number": "1" if state == "sync" else "2",
            "Content-Type": "application/json; utf-8",
        }
        
        try:
            response = requests.post(
                webhook_url,
                headers=headers,
                data="",
                timeout=30,
            )
            
            self.stdout.write(f"\nResponse: HTTP {response.status_code}")
            self.stdout.write(f"Body: {response.text}")
            
            if response.status_code == 200:
                self.stdout.write(
                    self.style.SUCCESS("\nWebhook accepted the notification!")
                )
                if state == "exists":
                    self.stdout.write("Check server logs for sync results.")
            elif response.status_code == 403:
                self.stdout.write(
                    self.style.ERROR("\nToken verification failed!")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"\nUnexpected status code: {response.status_code}")
                )
                
        except requests.exceptions.ConnectionError:
            raise CommandError(
                "Could not connect to webhook URL. "
                "Is the server running? Start with: python manage.py runserver"
            )
