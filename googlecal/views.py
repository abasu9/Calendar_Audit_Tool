"""
Web Views for Google Calendar Authorization and Event Preview

PURPOSE:
This module provides the Django views (page handlers) for:
1. Dashboard - Main page showing auth status and calendar preview
2. OAuth Start - Redirects user to Google's consent screen
3. OAuth Callback - Handles Google's redirect after user consents

URL ROUTES (defined in googlecal/urls.py):
- GET /                  -> dashboard()     - Main page
- GET /oauth2/start/     -> oauth_start()   - Start OAuth flow
- GET /oauth2/callback/  -> oauth_callback() - Handle Google's redirect

FLOW:
1. User visits / (dashboard)
2. If not authorized: shows "Connect Google Calendar" button
3. User clicks button -> /oauth2/start/ -> redirects to Google
4. User approves on Google -> Google redirects to /oauth2/callback/
5. We exchange code for tokens, save them, redirect to /
6. User visits / (dashboard) -> now shows calendar events
"""

import datetime
import logging
from zoneinfo import ZoneInfo

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from googleapiclient.errors import HttpError

from googlecal.client import GoogleAuthError, build_service, load_credentials, save_credentials
from googlecal.oauth import OAuthConfigError, authorization_url, fetch_credentials

logger = logging.getLogger(__name__)

# How many days of upcoming events to show on the dashboard
PREVIEW_DAYS = 7


def dashboard(request):
    """
    Main landing page showing authorization status and calendar preview.
    
    WHAT THIS DOES:
    1. Try to load existing Google credentials
    2. If no credentials: show "Connect" button with OAuth scopes listed
    3. If credentials exist: fetch and display upcoming calendar events
    
    TEMPLATE CONTEXT:
    - redirect_uri: The OAuth callback URL (user needs to register this in Google Console)
    - scopes: List of permission scopes we're requesting
    - preview_days: Number of days of events to show
    - authorized: Boolean - do we have valid credentials?
    - notice: Info message (e.g., "no credentials found")
    - error: Error message if something went wrong
    - calendar_id: The user's primary calendar email
    - calendar_timezone: The calendar's timezone setting
    - report_timezone: Our display timezone (from settings)
    - events: List of event dicts with summary, when, minutes, attendees
    - total_minutes: Sum of all timed event durations
    
    RETURNS:
    - Rendered HTML page using googlecal/dashboard.html template
    """
    # Base context - always needed for the template
    context = {
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "scopes": settings.GOOGLE_OAUTH_SCOPES,
        "preview_days": PREVIEW_DAYS,
        "authorized": False,
    }

    # Step 1: Try to load credentials
    try:
        credentials = load_credentials()
    except GoogleAuthError as exc:
        # No valid credentials - show the "Connect" page with notice
        context["notice"] = str(exc)
        return render(request, "googlecal/dashboard.html", context)

    # We have valid credentials!
    context["authorized"] = True

    # Step 2: Fetch calendar info and events
    try:
        service = build_service(credentials=credentials)
        # Get primary calendar metadata (id, timezone, etc.)
        calendar = service.calendars().get(calendarId="primary").execute()
        # Get upcoming events
        events = _upcoming_events(service, PREVIEW_DAYS)
    except (HttpError, GoogleAuthError) as exc:
        # API call failed (maybe token revoked, API quota exceeded, etc.)
        logger.warning("Calendar preview failed: %s", exc)
        context["error"] = str(exc)
        return render(request, "googlecal/dashboard.html", context)

    # Step 3: Format events for display
    tz = ZoneInfo(settings.REPORT_TIME_ZONE)
    context.update(
        {
            "calendar_id": calendar.get("id"),
            "calendar_timezone": calendar.get("timeZone"),
            "report_timezone": settings.REPORT_TIME_ZONE,
            "events": [_present(event, tz) for event in events],
            "total_minutes": sum(_duration_minutes(e) for e in events),
        }
    )
    return render(request, "googlecal/dashboard.html", context)


def oauth_start(request):
    """
    Start the OAuth flow by redirecting user to Google's consent screen.
    
    WHAT THIS DOES:
    1. Generate the Google authorization URL (includes client_id, scopes, redirect_uri)
    2. Save OAuth state and PKCE verifier in session (for the callback)
    3. Redirect the user to Google
    
    AFTER THIS:
    - User sees Google's consent screen
    - User clicks "Allow"
    - Google redirects to /oauth2/callback/ with ?code=XXX&state=YYY
    
    RETURNS:
    - HTTP 302 redirect to accounts.google.com
    - Or error page if configuration is wrong
    """
    try:
        # authorization_url() generates the URL and saves state to session
        return redirect(authorization_url(request))
    except OAuthConfigError as exc:
        # Something wrong with credentials.json
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": str(exc), "authorized": False},
            status=500,
        )


def oauth_callback(request):
    """
    Handle Google's redirect after user consents (or denies).
    
    WHAT THIS DOES:
    1. Check if Google sent an error (user denied, or something went wrong)
    2. If success: exchange the authorization code for tokens
    3. Save the tokens to token.json
    4. Redirect to dashboard to show the calendar
    
    QUERY PARAMETERS FROM GOOGLE:
    - code: The authorization code to exchange for tokens
    - state: The random string we sent (for CSRF verification)
    - error: Present if user denied or something went wrong
    - error_description: Human-readable error message
    
    RETURNS:
    - HTTP 302 redirect to / (dashboard) on success
    - Error page on failure
    """
    # Check if Google sent an error
    if error := request.GET.get("error"):
        description = request.GET.get("error_description", "")
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": f"Google denied the request: {error}. {description}".strip()},
            status=400,
        )

    # Exchange the authorization code for tokens
    try:
        credentials = fetch_credentials(request)
    except OAuthConfigError as exc:
        # State mismatch, missing verifier, etc.
        return render(
            request, "googlecal/dashboard.html", {"error": str(exc)}, status=400
        )
    except Exception as exc:  # noqa: BLE001 - surface the provider's message
        # Unexpected error during token exchange
        logger.exception("Token exchange failed")
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": f"Token exchange failed: {exc}"},
            status=400,
        )

    # Save the credentials for future use
    save_credentials(credentials)
    logger.info("Stored Google credentials at %s", settings.GOOGLE_TOKEN_FILE)
    
    # Redirect to dashboard to show the calendar
    return redirect(reverse("dashboard"))


def _upcoming_events(service, days):
    """
    Fetch all events in the next N days from the primary calendar.
    
    WHAT THIS DOES:
    1. Calculate the time window (now to now + days)
    2. Call the Calendar API to list events
    3. Handle pagination (API returns max 250 events per page)
    4. Return all events as a list
    
    API PARAMETERS:
    - calendarId="primary": The user's main calendar
    - timeMin/timeMax: ISO format datetime bounds
    - singleEvents=True: Expand recurring events into individual instances
      (e.g., "Weekly standup" becomes separate events for each week)
    - orderBy="startTime": Sort chronologically (requires singleEvents=True)
    - maxResults=250: Page size (maximum allowed by the API)
    - pageToken: For getting subsequent pages
    
    PARAMETERS:
    - service: Google Calendar API client
    - days: Number of days to look ahead
    
    RETURNS:
    - List of event dicts from the API
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    time_max = now + datetime.timedelta(days=days)

    events = []
    page_token = None
    
    # Loop through pages until we have all events
    while True:
        response = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,  # Expand recurring events
                orderBy="startTime",
                maxResults=250,  # Maximum per page
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            # No more pages
            return events


def _duration_minutes(event):
    """
    Calculate the duration of an event in minutes.
    
    WHAT THIS DOES:
    - For timed events: parse start and end times, calculate difference
    - For all-day events: return 0 (they span full days, not meeting time)
    
    HOW GOOGLE REPRESENTS EVENT TIMES:
    - Timed events: {"start": {"dateTime": "2024-01-01T09:00:00-06:00"}}
    - All-day events: {"start": {"date": "2024-01-01"}}
    
    PARAMETERS:
    - event: Event dict from the Calendar API
    
    RETURNS:
    - Integer minutes, or 0 for all-day events
    """
    start_raw = event["start"].get("dateTime")
    if start_raw is None:
        # All-day event - no "meeting time" to count
        return 0
    start = datetime.datetime.fromisoformat(start_raw)
    end = datetime.datetime.fromisoformat(event["end"]["dateTime"])
    return int((end - start).total_seconds() // 60)


def _present(event, tz):
    """
    Transform a Google Calendar event into a template-friendly dict.
    
    WHAT THIS DOES:
    - Extract the fields we want to display
    - Format the datetime for human reading
    - Convert to the display timezone
    - Handle both timed and all-day events
    
    PARAMETERS:
    - event: Event dict from the Calendar API
    - tz: ZoneInfo timezone for display
    
    RETURNS:
    Dict with:
    - summary: Event title (or "(no title)")
    - when: Formatted datetime string like "Mon 01 Jan 09:00 - 10:00"
    - all_day: Boolean
    - minutes: Duration in minutes (0 for all-day)
    - attendee_count: Number of attendees
    - organizer: Organizer's email
    """
    start_raw = event["start"].get("dateTime")
    attendees = event.get("attendees") or []

    # All-day event handling
    if start_raw is None:
        return {
            "summary": event.get("summary", "(no title)"),
            "when": event["start"]["date"],  # Just the date, e.g., "2024-01-01"
            "all_day": True,
            "minutes": 0,
            "attendee_count": len(attendees),
            "organizer": (event.get("organizer") or {}).get("email", ""),
        }

    # Timed event handling
    start = datetime.datetime.fromisoformat(start_raw).astimezone(tz)
    end = datetime.datetime.fromisoformat(event["end"]["dateTime"]).astimezone(tz)
    return {
        "summary": event.get("summary", "(no title)"),
        "when": f"{start:%a %d %b %H:%M} - {end:%H:%M}",  # e.g., "Mon 01 Jan 09:00 - 10:00"
        "all_day": False,
        "minutes": _duration_minutes(event),
        "attendee_count": len(attendees),
        "organizer": (event.get("organizer") or {}).get("email", ""),
    }
