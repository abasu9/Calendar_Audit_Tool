"""Render the main dashboard and handle Google OAuth redirects.

The dashboard shows a connection action until credentials exist, then loads a
seven-day calendar preview. The other views start authorization and turn Google's
callback code into saved credentials.
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

# Keep the landing-page preview short and useful.
PREVIEW_DAYS = 7


def dashboard(request):
    """Show connection status and an upcoming primary-calendar preview.

    The view loads credentials without opening a browser. Connected users receive
    calendar details, formatted events, and total meeting minutes; configuration
    or API failures are placed in the template context for a readable page.
    """
    context = {
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "scopes": settings.GOOGLE_OAUTH_SCOPES,
        "preview_days": PREVIEW_DAYS,
        "authorized": False,
    }

    try:
        credentials = load_credentials()
    except GoogleAuthError as exc:
        context["notice"] = str(exc)
        return render(request, "googlecal/dashboard.html", context)

    context["authorized"] = True

    try:
        service = build_service(credentials=credentials)
        calendar = service.calendars().get(calendarId="primary").execute()
        events = _upcoming_events(service, PREVIEW_DAYS)
    except (HttpError, GoogleAuthError) as exc:
        logger.warning("Calendar preview failed: %s", exc)
        context["error"] = str(exc)
        return render(request, "googlecal/dashboard.html", context)

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
    """Start OAuth by redirecting the browser to Google's consent page.

    ``authorization_url`` also saves state and PKCE data in the session. Invalid
    client configuration is rendered on the dashboard instead of redirecting.
    """
    try:
        return redirect(authorization_url(request))
    except OAuthConfigError as exc:
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": str(exc), "authorized": False},
            status=500,
        )


def oauth_callback(request):
    """Finish OAuth after Google redirects the browser back.

    Provider errors are shown directly. A successful callback validates the session,
    exchanges the authorization code, saves credentials, and returns the user to the
    dashboard.
    """
    if error := request.GET.get("error"):
        description = request.GET.get("error_description", "")
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": f"Google denied the request: {error}. {description}".strip()},
            status=400,
        )

    try:
        credentials = fetch_credentials(request)
    except OAuthConfigError as exc:
        return render(
            request, "googlecal/dashboard.html", {"error": str(exc)}, status=400
        )
    except Exception as exc:  # noqa: BLE001 - surface the provider's message
        logger.exception("Token exchange failed")
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": f"Token exchange failed: {exc}"},
            status=400,
        )

    save_credentials(credentials)
    logger.info("Stored Google credentials at %s", settings.GOOGLE_TOKEN_FILE)

    from calsync.bootstrap import start_bootstrap
    start_bootstrap("primary")

    return redirect(reverse("dashboard"))


def _upcoming_events(service, days):
    """Return every primary-calendar event in the next number of days.

    The helper expands recurring rules, requests chronological results, and follows
    page tokens until Google's full response window has been collected.
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    time_max = now + datetime.timedelta(days=days)

    events = []
    page_token = None
    
    while True:
        response = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
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


def _duration_minutes(event):
    """Return a timed event's whole-minute duration.

    Google all-day items have dates instead of datetimes and return zero because
    the dashboard counts meeting time rather than calendar-day coverage.
    """
    start_raw = event["start"].get("dateTime")
    if start_raw is None:
        return 0
    start = datetime.datetime.fromisoformat(start_raw)
    end = datetime.datetime.fromisoformat(event["end"]["dateTime"])
    return int((end - start).total_seconds() // 60)


def _present(event, tz):
    """Convert one Google event into values used by the dashboard template.

    Titles and meeting details are copied into a small dictionary. All-day events
    keep their date; timed events are converted to the report timezone and receive
    a readable start-to-end label.
    """
    start_raw = event["start"].get("dateTime")
    attendees = event.get("attendees") or []

    if start_raw is None:
        return {
            "summary": event.get("summary", "(no title)"),
            "when": event["start"]["date"],
            "all_day": True,
            "minutes": 0,
            "attendee_count": len(attendees),
            "organizer": (event.get("organizer") or {}).get("email", ""),
        }

    start = datetime.datetime.fromisoformat(start_raw).astimezone(tz)
    end = datetime.datetime.fromisoformat(event["end"]["dateTime"]).astimezone(tz)
    return {
        "summary": event.get("summary", "(no title)"),
        "when": f"{start:%a %d %b %H:%M} - {end:%H:%M}",
        "all_day": False,
        "minutes": _duration_minutes(event),
        "attendee_count": len(attendees),
        "organizer": (event.get("organizer") or {}).get("email", ""),
    }
