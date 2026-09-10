"""Render the main dashboard and handle Google OAuth sign-in.

The dashboard shows a sign-in prompt for anonymous visitors, and a calendar
preview for authenticated users. The OAuth start and callback views implement
Google Sign-In: after consent, the callback creates or retrieves the Django user,
logs them in, saves their credentials to the database, and kicks off the
background bootstrap (full sync + push channel registration).
"""

import datetime
import logging
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.urls import reverse
from googleapiclient.errors import HttpError

from googlecal.client import GoogleAuthError, build_service, load_credentials, save_credentials
from googlecal.oauth import OAuthConfigError, authorization_url, fetch_credentials, verify_id_token

logger = logging.getLogger(__name__)
User = get_user_model()

# Keep the landing-page preview short and useful.
PREVIEW_DAYS = 7


def dashboard(request):
    """Show sign-in prompt for anonymous visitors; calendar preview for authenticated users."""
    if request.user.is_anonymous:
        return render(
            request,
            "googlecal/dashboard.html",
            {
                "authorized": False,
                "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                "scopes": settings.GOOGLE_OAUTH_SCOPES,
            },
        )

    context = {
        "authorized": False,
        "user_email": request.user.email,
        "preview_days": PREVIEW_DAYS,
    }

    try:
        credentials = load_credentials(request.user)
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
    """Start OAuth by redirecting the browser to Google's consent page."""
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
    """Finish OAuth: identify the user, create their account, log them in, and bootstrap."""
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Token exchange failed")
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": f"Token exchange failed: {exc}"},
            status=400,
        )

    try:
        identity = verify_id_token(credentials)
    except OAuthConfigError as exc:
        return render(
            request,
            "googlecal/dashboard.html",
            {"error": str(exc)},
            status=400,
        )

    user = _resolve_user(identity)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    save_credentials(user, credentials, identity=identity)
    logger.info("User %s signed in via Google (%s)", user.username, identity["email"])

    from calsync.bootstrap import start_bootstrap
    start_bootstrap(user_id=user.id)

    return redirect(reverse("dashboard"))


def logout_view(request):
    """Sign out the current user and redirect to the dashboard."""
    logout(request)
    return redirect(reverse("dashboard"))


def _resolve_user(identity: dict):
    """Return the Django user matching *identity*, creating one when needed.

    Looks up an existing ``GoogleCredential`` by ``google_sub`` first — this
    handles every subsequent sign-in with zero ambiguity. Falls back to matching
    on email in case an account was created before ``google_sub`` was stored.
    Creates a new user when no match is found.
    """
    from googlecal.models import GoogleCredential

    sub = identity["sub"]
    email = identity.get("email", "")

    # Fastest path: credential row already links sub to a Django user.
    try:
        return GoogleCredential.objects.get(google_sub=sub).user
    except GoogleCredential.DoesNotExist:
        pass

    # Email fallback: a user whose account predates google_sub storage.
    if email:
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist:
            pass

    # New user: derive a username from the email local-part; ensure uniqueness.
    base_username = (email.split("@")[0] if email else sub)[:150]
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=email,
    )
    user.set_unusable_password()
    user.save()
    logger.info("Created new user %s (%s)", username, email)
    return user


def _upcoming_events(service, days):
    """Return every primary-calendar event in the next number of days."""
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
    """Return a timed event's whole-minute duration; zero for all-day events."""
    start_raw = event["start"].get("dateTime")
    if start_raw is None:
        return 0
    start = datetime.datetime.fromisoformat(start_raw)
    end = datetime.datetime.fromisoformat(event["end"]["dateTime"])
    return int((end - start).total_seconds() // 60)


def _present(event, tz):
    """Convert one Google event into values used by the dashboard template."""
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
