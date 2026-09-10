"""Register a Google Calendar push-notification channel for local development.

Reads the running ngrok tunnel's HTTPS URL automatically, then calls
``ensure_watch_channel`` to register (or renew) a channel pointing at the local
server. Refuses to run outside of DEBUG mode so it cannot become a production
workaround.

USAGE
-----
Start ngrok first::

    ngrok http 8000

Then in another terminal::

    python manage.py dev_watch

To override the auto-detected URL (other tunnel providers, static domain, etc.)::

    python manage.py dev_watch --url https://my-static.ngrok-free.app

To stop the active channel when tearing down the tunnel::

    python manage.py dev_watch --stop
"""

import urllib.request
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from calsync.watch import ensure_watch_channel, stop_watch_channel
from calsync.models import WatchChannel

NGROK_API = "http://127.0.0.1:4040/api/tunnels"


def _detect_ngrok_url() -> str:
    """Read the HTTPS tunnel URL from ngrok's local API.

    Returns an empty string when ngrok is not running or has no HTTPS tunnel.
    """
    try:
        with urllib.request.urlopen(NGROK_API, timeout=3) as response:
            data = json.loads(response.read())
        for tunnel in data.get("tunnels", []):
            public_url = tunnel.get("public_url", "")
            if public_url.startswith("https://"):
                return public_url.rstrip("/")
    except Exception:
        pass
    return ""


class Command(BaseCommand):
    """Register or stop a local Google Calendar push-notification channel."""

    help = (
        "Register a Google Calendar push-notification channel for local ngrok "
        "development. Auto-detects the running ngrok HTTPS tunnel."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            default="",
            help=(
                "Override the webhook base URL (default: auto-detect from ngrok). "
                "Must be HTTPS."
            ),
        )
        parser.add_argument(
            "--calendar",
            type=str,
            default="primary",
            help="Calendar ID to watch (default: primary).",
        )
        parser.add_argument(
            "--stop",
            action="store_true",
            default=False,
            help="Stop all active channels for the calendar instead of creating one.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "dev_watch may only run when DEBUG is True. "
                "In production, set PUBLIC_BASE_URL instead."
            )

        calendar_id = options["calendar"]

        # --stop: deactivate channels and exit.
        if options["stop"]:
            channels = WatchChannel.objects.filter(calendar_id=calendar_id, active=True)
            if not channels.exists():
                self.stdout.write(
                    self.style.WARNING(f"No active channels found for {calendar_id}.")
                )
                return
            for ch in channels:
                success = stop_watch_channel(str(ch.channel_id))
                if success:
                    self.stdout.write(
                        self.style.SUCCESS(f"Stopped channel {ch.channel_id}")
                    )
                else:
                    self.stderr.write(
                        self.style.ERROR(f"Failed to stop channel {ch.channel_id}")
                    )
            return

        # Resolve the webhook URL.
        base_url = options["url"].rstrip("/") if options["url"] else _detect_ngrok_url()

        if not base_url:
            raise CommandError(
                "Could not detect an ngrok HTTPS tunnel. "
                "Is ngrok running? (ngrok http 8000)\n"
                "Or pass --url https://your-tunnel.ngrok-free.app"
            )

        if not base_url.startswith("https://"):
            raise CommandError(
                f"URL must start with https://. Got: {base_url}\n"
                "Google requires a valid TLS certificate to deliver notifications."
            )

        webhook_url = f"{base_url}/api/webhook/"

        self.stdout.write(f"Registering channel for {calendar_id} → {webhook_url}")

        channel = ensure_watch_channel(
            calendar_id=calendar_id,
            webhook_url=webhook_url,
        )

        if channel:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Channel ready: {channel.channel_id}\n"
                    f"Expires: {channel.expiration.isoformat()}\n"
                    f"Webhook: {channel.webhook_url}"
                )
            )
        else:
            raise CommandError(
                "Failed to register a watch channel. "
                "Check the server logs for details."
            )
