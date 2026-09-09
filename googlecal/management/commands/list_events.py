"""List past or upcoming Google Calendar events in the terminal.

The command authenticates with Google, reads every event in the requested time
window, and prints times in the report timezone.
"""

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from googleapiclient.errors import HttpError

from googlecal.client import GoogleAuthError, build_service, load_credentials


class Command(BaseCommand):
    """Expose a readable calendar preview as a Django command."""
    
    help = "List events from the primary Google Calendar."

    def add_arguments(self, parser):
        """Register the window, direction, and interactive-login options.

        Django parses these values and passes them to ``handle`` with safe defaults.
        """
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Size of the window to fetch, in days (default: 7).",
        )
        parser.add_argument(
            "--past",
            action="store_true",
            help="Look backwards from now instead of forwards.",
        )
        parser.add_argument(
            "--authorize",
            action="store_true",
            help="Allow the browser consent flow if no valid token exists yet.",
        )

    def handle(self, *args, **options):
        """Fetch the selected time window and print its events.

        The method validates the day count, loads credentials, calculates a past
        or future range, and converts API or authentication failures into clear
        command errors.
        """
        days = options["days"]
        if days <= 0:
            raise CommandError("--days must be positive")

        try:
            creds = load_credentials(allow_interactive=options["authorize"])
            service = build_service(credentials=creds)
        except GoogleAuthError as exc:
            raise CommandError(str(exc)) from exc

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        window = datetime.timedelta(days=days)
        time_min, time_max = (now - window, now) if options["past"] else (now, now + window)

        try:
            calendar = service.calendars().get(calendarId="primary").execute()
            events = self._fetch_events(service, time_min, time_max)
        except HttpError as exc:
            raise CommandError(f"Google Calendar API error: {exc}") from exc

        tz = ZoneInfo(settings.REPORT_TIME_ZONE)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Primary calendar: {calendar.get('id')} "
                f"(calendar tz {calendar.get('timeZone')})"
            )
        )
        
        self.stdout.write(
            f"Window: {time_min.astimezone(tz):%Y-%m-%d %H:%M} to "
            f"{time_max.astimezone(tz):%Y-%m-%d %H:%M} ({settings.REPORT_TIME_ZONE})"
        )
        self.stdout.write(f"Events found: {len(events)}\n")

        if not events:
            self.stdout.write("No events in this window.")
            return

        for event in events:
            self.stdout.write(self._format_event(event, tz))

    def _fetch_events(self, service, time_min, time_max):
        """Return every event inside the supplied time range.

        The helper follows Google's page tokens until no page remains. Recurring
        rules are expanded into individual meetings and results are ordered by
        start time.
        """
        events = []
        page_token = None
        while True:
            response = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                )
                .execute()
            )
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return events

    def _format_event(self, event, tz):
        """Convert one Google event into a compact terminal line.

        All-day events display only a date. Timed events are converted to the
        report timezone and include duration and attendee count when available.
        """
        start_raw = event["start"].get("dateTime")
        summary = event.get("summary", "(no title)")

        if start_raw is None:
            return f"  {event['start']['date']}  (all day)      {summary}"

        start = datetime.datetime.fromisoformat(start_raw).astimezone(tz)
        end = datetime.datetime.fromisoformat(event["end"]["dateTime"]).astimezone(tz)
        minutes = int((end - start).total_seconds() // 60)
        attendees = len(event.get("attendees") or [])
        suffix = f"  [{attendees} attendees]" if attendees else ""
        return (
            f"  {start:%Y-%m-%d %H:%M}-{end:%H:%M}  {minutes:>4}m  {summary}{suffix}"
        )
