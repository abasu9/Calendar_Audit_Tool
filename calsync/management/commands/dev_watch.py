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

To target a specific user account::

    python manage.py dev_watch --user alice@example.com

To override the auto-detected URL (other tunnel providers, static domain, etc.)::

    python manage.py dev_watch --url https://my-static.ngrok-free.app

To stop the active channel when tearing down the tunnel::

    python manage.py dev_watch --stop
"""

import json
import urllib.request

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from calsync.models import WatchChannel
from calsync.watch import ensure_watch_channel, stop_watch_channel

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
            "--user",
            type=str,
            default="",
            metavar="EMAIL",
            help=(
                "Email of the user whose calendar to watch. "
                "Defaults to the only user in the database when there is exactly one."
            ),
        )
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

    def _resolve_user(self, email: str):
        """Return the Django user identified by *email* or the only existing user.

        Raises ``CommandError`` when the email is not found or when *email* is
        absent and there is not exactly one user in the database.
        """
        User = get_user_model()

        if email:
            try:
                return User.objects.get(email=email)
            except User.DoesNotExist:
                raise CommandError(
                    f"No user with email '{email}'. "
                    "Make sure the user has signed in at least once."
                )

        # No --user flag: auto-select when there is exactly one user.
        count = User.objects.count()
        if count == 0:
            raise CommandError(
                "No users exist yet. Sign in via the browser first, then run dev_watch."
            )
        if count > 1:
            emails = ", ".join(User.objects.values_list("email", flat=True))
            raise CommandError(
                f"Multiple users exist ({emails}). "
                "Pass --user EMAIL to choose one."
            )
        return User.objects.first()

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "dev_watch may only run when DEBUG is True. "
                "In production, set PUBLIC_BASE_URL instead."
            )

        calendar_id = options["calendar"]
        user = self._resolve_user(options["user"])

        self.stdout.write(f"User: {user.email or user.username}")

        # --stop: deactivate channels and exit.
        if options["stop"]:
            channels = WatchChannel.objects.filter(
                user=user, calendar_id=calendar_id, active=True
            )
            if not channels.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"No active channels found for {calendar_id} (user {user.email})."
                    )
                )
                return
            for ch in channels:
                success = stop_watch_channel(str(ch.channel_id), user=user)
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

        self.stdout.write(
            f"Registering channel for user={user.email} calendar={calendar_id} → {webhook_url}"
        )

        channel = ensure_watch_channel(
            user=user,
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
