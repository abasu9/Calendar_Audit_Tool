"""
Django Management Command: list_events

PURPOSE:
Print calendar events from the command line. Useful for:
- Testing that the Google Calendar API works through Django
- Quick inspection of your calendar without opening the browser
- Automation/scripting

USAGE:
    # Show next 7 days (default)
    python manage.py list_events
    
    # Show next 30 days
    python manage.py list_events --days 30
    
    # Show last 14 days
    python manage.py list_events --days 14 --past
    
    # If no token.json exists, this will fail. Use the web flow instead.
    # (The --authorize flag was for desktop OAuth clients, which we're not using)

OUTPUT EXAMPLE:
    Primary calendar: user@gmail.com (calendar tz America/Chicago)
    Window: 2024-01-01 09:00 to 2024-01-08 09:00 (America/Chicago)
    Events found: 5

      2024-01-02 09:00-10:00    60m  Team Standup  [4 attendees]
      2024-01-02 14:00-15:00    60m  1:1 with Manager
      2024-01-03  (all day)         Company Holiday
      ...
"""

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from googleapiclient.errors import HttpError

from googlecal.client import GoogleAuthError, build_service, load_credentials


class Command(BaseCommand):
    """
    Django management command to list Google Calendar events.
    
    Inherits from BaseCommand which provides:
    - Argument parsing (add_arguments method)
    - stdout/stderr handling with color support
    - Standard Django command conventions
    """
    
    # Help text shown when running: python manage.py list_events --help
    help = "List events from the primary Google Calendar."

    def add_arguments(self, parser):
        """
        Define command-line arguments.
        
        ARGUMENTS:
        --days N     : Size of the time window in days (default: 7)
        --past       : Look backwards instead of forwards
        --authorize  : Allow browser-based OAuth (only works with desktop clients)
        
        EXAMPLES:
        python manage.py list_events --days 30           # Next 30 days
        python manage.py list_events --days 7 --past     # Last 7 days
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
        """
        Main entry point for the command. Called by Django when you run the command.
        
        WHAT THIS DOES:
        1. Validate arguments
        2. Load Google credentials
        3. Calculate the time window (past or future)
        4. Fetch calendar metadata and events from Google
        5. Print formatted output
        
        PARAMETERS:
        - args: Positional arguments (unused)
        - options: Dict of parsed arguments (days, past, authorize)
        
        RAISES:
        - CommandError: If arguments are invalid or API calls fail
        """
        days = options["days"]
        if days <= 0:
            raise CommandError("--days must be positive")

        # Step 1: Load credentials
        try:
            creds = load_credentials(allow_interactive=options["authorize"])
            service = build_service(credentials=creds)
        except GoogleAuthError as exc:
            raise CommandError(str(exc)) from exc

        # Step 2: Calculate time window
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        window = datetime.timedelta(days=days)
        # If --past: look backwards (time_min = now - window, time_max = now)
        # Otherwise: look forwards (time_min = now, time_max = now + window)
        time_min, time_max = (now - window, now) if options["past"] else (now, now + window)

        # Step 3: Fetch data from Google
        try:
            calendar = service.calendars().get(calendarId="primary").execute()
            events = self._fetch_events(service, time_min, time_max)
        except HttpError as exc:
            raise CommandError(f"Google Calendar API error: {exc}") from exc

        # Step 4: Print results
        tz = ZoneInfo(settings.REPORT_TIME_ZONE)
        
        # Header with calendar info
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Primary calendar: {calendar.get('id')} "
                f"(calendar tz {calendar.get('timeZone')})"
            )
        )
        
        # Time window info
        self.stdout.write(
            f"Window: {time_min.astimezone(tz):%Y-%m-%d %H:%M} to "
            f"{time_max.astimezone(tz):%Y-%m-%d %H:%M} ({settings.REPORT_TIME_ZONE})"
        )
        self.stdout.write(f"Events found: {len(events)}\n")

        # Events list
        if not events:
            self.stdout.write("No events in this window.")
            return

        for event in events:
            self.stdout.write(self._format_event(event, tz))

    def _fetch_events(self, service, time_min, time_max):
        """
        Fetch all events in the specified time window.
        
        WHAT THIS DOES:
        - Call Google Calendar API's events.list endpoint
        - Handle pagination (API returns max 250 events per request)
        - Use singleEvents=True to expand recurring events
        
        WHY singleEvents=True?
        Recurring events (like "Weekly standup every Monday") are stored as a single
        record with recurrence rules. singleEvents=True tells Google to expand these
        into individual instances. This is essential for audit metrics - we need to
        count actual meetings, not just the rule that says "repeat weekly".
        
        PARAMETERS:
        - service: Google Calendar API client
        - time_min: Start of window (datetime)
        - time_max: End of window (datetime)
        
        RETURNS:
        - List of event dicts from the API
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
                    singleEvents=True,  # Expand recurring events into instances
                    orderBy="startTime",  # Chronological order
                    maxResults=250,  # Max allowed per page
                    pageToken=page_token,
                )
                .execute()
            )
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return events

    def _format_event(self, event, tz):
        """
        Format a single event for console output.
        
        WHAT THIS DOES:
        - Parse the event's start/end times
        - Calculate duration
        - Format nicely for terminal display
        
        OUTPUT FORMAT:
        - Timed event: "  2024-01-02 09:00-10:00    60m  Meeting Name  [3 attendees]"
        - All-day:     "  2024-01-02  (all day)         Holiday"
        
        PARAMETERS:
        - event: Event dict from Google Calendar API
        - tz: ZoneInfo timezone for display
        
        RETURNS:
        - Formatted string for one event
        """
        start_raw = event["start"].get("dateTime")
        summary = event.get("summary", "(no title)")

        if start_raw is None:
            # All-day event: only has a date, no time
            return f"  {event['start']['date']}  (all day)      {summary}"

        # Timed event: parse and format
        start = datetime.datetime.fromisoformat(start_raw).astimezone(tz)
        end = datetime.datetime.fromisoformat(event["end"]["dateTime"]).astimezone(tz)
        minutes = int((end - start).total_seconds() // 60)
        attendees = len(event.get("attendees") or [])
        suffix = f"  [{attendees} attendees]" if attendees else ""
        return (
            f"  {start:%Y-%m-%d %H:%M}-{end:%H:%M}  {minutes:>4}m  {summary}{suffix}"
        )
