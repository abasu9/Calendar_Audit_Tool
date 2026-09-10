"""Calculate dashboard metrics from synchronized calendar events.

Each query limits data to a recent time window and returns JSON-friendly values.
All-day, tentative, and cancelled entries are excluded from meeting-time metrics
so the report reflects completed, timed meetings.

Every public function accepts a *user* argument and filters all querysets to that
user's events so data from different accounts never mixes.
"""

from datetime import timedelta
from django.db.models import Count, Max, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

from calsync.models import CalendarEvent, EventAttendee


def get_monthly_meeting_time(user, months: int = 3) -> list[dict]:
    """Return total confirmed meeting time for each recent month for *user*.

    The cutoff uses 30 days per requested month. Django groups timed events by
    their start month and sums durations, then the result is formatted with month
    keys, readable labels, minutes, and rounded hours.
    """
    # The project consistently treats one report month as 30 days.
    cutoff = timezone.now() - timedelta(days=months * 30)

    queryset = (
        CalendarEvent.objects
        .filter(
            user=user,
            start_time__gte=cutoff,
            all_day=False,
            status="confirmed",
        )
        .annotate(month=TruncMonth("start_time"))
        .values("month")
        .annotate(total_minutes=Sum("duration_minutes"))
        .order_by("month")
    )

    results = []
    for row in queryset:
        month_date = row["month"]
        total_minutes = row["total_minutes"] or 0

        results.append({
            "month": month_date.strftime("%Y-%m"),
            "label": month_date.strftime("%B %Y"),
            "total_minutes": total_minutes,
            "total_hours": round(total_minutes / 60, 2),
        })

    return results


def get_meeting_extremes(user, months: int = 3) -> dict:
    """Return the recent months with the highest and lowest meeting counts for *user*.

    Confirmed timed events are grouped by month and counted. The formatted monthly
    list is returned with Python-selected maximum and minimum entries, or ``None``
    values when no meetings match.
    """
    cutoff = timezone.now() - timedelta(days=months * 30)

    queryset = (
        CalendarEvent.objects
        .filter(
            user=user,
            start_time__gte=cutoff,
            all_day=False,
            status="confirmed",
        )
        .annotate(month=TruncMonth("start_time"))
        .values("month")
        .annotate(meeting_count=Count("id"))
        .order_by("month")
    )

    all_months = []
    for row in queryset:
        month_date = row["month"]
        meeting_count = row["meeting_count"] or 0

        all_months.append({
            "month": month_date.strftime("%Y-%m"),
            "label": month_date.strftime("%B %Y"),
            "meeting_count": meeting_count,
        })

    if all_months:
        highest = max(all_months, key=lambda x: x["meeting_count"])
        lowest = min(all_months, key=lambda x: x["meeting_count"])
    else:
        highest = None
        lowest = None

    return {
        "highest": highest,
        "lowest": lowest,
        "all_months": all_months,
    }


# Dashboard labels use these meeting-time boundaries.
BUSY_THRESHOLD_MINUTES = 300
RELAXED_THRESHOLD_MINUTES = 120


def classify_week(total_minutes: int) -> str:
    """Label a weekly meeting total as busy, relaxed, or normal.

    Totals above five hours are busy and totals below two hours are relaxed. Values
    on or between those boundaries are normal for dashboard color coding.
    """
    if total_minutes > BUSY_THRESHOLD_MINUTES:
        return "busy"
    elif total_minutes < RELAXED_THRESHOLD_MINUTES:
        return "relaxed"
    else:
        return "normal"


def get_weekly_extremes(user, months: int = 3) -> dict:
    """Return the recent weeks with the most and least meeting time for *user*.

    Confirmed timed events are grouped into Monday-based weeks, counted, summed,
    and classified. The result includes readable dates, configured thresholds, the
    complete weekly list, and the maximum and minimum entries.
    """
    cutoff = timezone.now() - timedelta(days=months * 30)

    queryset = (
        CalendarEvent.objects
        .filter(
            user=user,
            start_time__gte=cutoff,
            all_day=False,
            status="confirmed",
        )
        .annotate(week=TruncWeek("start_time"))
        .values("week")
        .annotate(
            meeting_count=Count("id"),
            total_minutes=Sum("duration_minutes"),
        )
        .order_by("week")
    )

    all_weeks = []
    for row in queryset:
        week_start = row["week"]
        meeting_count = row["meeting_count"] or 0
        total_minutes = row["total_minutes"] or 0

        week_end = week_start + timedelta(days=6)
        iso_week = week_start.strftime("%G-W%V")

        all_weeks.append({
            "week": iso_week,
            "start_date": week_start.strftime("%Y-%m-%d"),
            "end_date": week_end.strftime("%Y-%m-%d"),
            "meeting_count": meeting_count,
            "total_minutes": total_minutes,
            "total_hours": round(total_minutes / 60, 2),
            "classification": classify_week(total_minutes),
        })

    if all_weeks:
        busiest = max(all_weeks, key=lambda x: x["total_minutes"])
        most_relaxed = min(all_weeks, key=lambda x: x["total_minutes"])
    else:
        busiest = None
        most_relaxed = None

    return {
        "threshold": {
            "busy_minutes": BUSY_THRESHOLD_MINUTES,
            "relaxed_minutes": RELAXED_THRESHOLD_MINUTES,
        },
        "busiest": busiest,
        "most_relaxed": most_relaxed,
        "all_weeks": all_weeks,
    }


def get_weekly_averages(user, months: int = 3) -> dict:
    """Return average meeting count and duration for *user*'s active recent weeks.

    Events are grouped by week and their counts and minutes are totaled. Averages
    divide those totals only by weeks containing at least one meeting; when no data
    exists, all average values are zero.
    """
    cutoff = timezone.now() - timedelta(days=months * 30)

    queryset = (
        CalendarEvent.objects
        .filter(
            user=user,
            start_time__gte=cutoff,
            all_day=False,
            status="confirmed",
        )
        .annotate(week=TruncWeek("start_time"))
        .values("week")
        .annotate(
            meeting_count=Count("id"),
            total_minutes=Sum("duration_minutes"),
        )
        .order_by("week")
    )

    weekly_data = []
    total_meetings = 0
    total_minutes = 0

    for row in queryset:
        week_start = row["week"]
        meeting_count = row["meeting_count"] or 0
        minutes = row["total_minutes"] or 0

        iso_week = week_start.strftime("%G-W%V")

        weekly_data.append({
            "week": iso_week,
            "start_date": week_start.strftime("%Y-%m-%d"),
            "meeting_count": meeting_count,
            "total_minutes": minutes,
        })

        total_meetings += meeting_count
        total_minutes += minutes

    weeks_analyzed = len(weekly_data)

    if weeks_analyzed > 0:
        avg_meetings = round(total_meetings / weeks_analyzed, 2)
        avg_minutes = round(total_minutes / weeks_analyzed, 2)
        avg_hours = round(avg_minutes / 60, 2)
    else:
        avg_meetings = 0
        avg_minutes = 0
        avg_hours = 0

    return {
        "weeks_analyzed": weeks_analyzed,
        "average_meetings_per_week": avg_meetings,
        "average_minutes_per_week": avg_minutes,
        "average_hours_per_week": avg_hours,
        "weekly_data": weekly_data,
    }


def get_top_contacts(user, months: int = 3, limit: int = 3) -> dict:
    """Return the people who appear most often in *user*'s recent meetings.

    Attendees are queried from the ``EventAttendee`` table as a single indexed
    aggregate — no JSON parsing, no Python loops over event rows. The calendar
    owner (``is_self=True``) is excluded at the database level. Contacts are
    ranked by meeting count descending, then by total shared minutes descending
    to break ties, and the requested limit is applied to the sorted result.
    """
    cutoff = timezone.now() - timedelta(days=months * 30)

    rows = (
        EventAttendee.objects
        .filter(
            user=user,
            is_self=False,
            event__start_time__gte=cutoff,
            event__all_day=False,
            event__status="confirmed",
        )
        .values("email")
        .annotate(
            meeting_count=Count("event_id"),
            total_minutes=Sum("event__duration_minutes"),
            name=Max("display_name"),
        )
        .order_by("-meeting_count", "-total_minutes")
    )

    all_contacts = [
        {
            "email": row["email"],
            "name": row["name"] or "",
            "meeting_count": row["meeting_count"],
            "total_minutes": row["total_minutes"] or 0,
            "total_hours": round((row["total_minutes"] or 0) / 60, 2),
        }
        for row in rows
    ]

    return {
        "top_contacts": all_contacts[:limit],
        "all_contacts": all_contacts,
    }


# Event titles containing any of these words count as recruiting activity.
INTERVIEW_KEYWORDS = [
    "interview",
    "candidate",
    "recruiting",
    "recruitment",
    "phone screen",
    "screening",
    "hiring",
]


def get_interview_time(user, months: int = 3) -> dict:
    """Return time spent in *user*'s meetings whose titles suggest recruiting work.

    A case-insensitive OR query matches any configured keyword. Matching confirmed,
    timed events are totaled, grouped by month, and returned individually so the
    dashboard can show both the summary and its supporting meetings.
    """
    from django.db.models import Q

    cutoff = timezone.now() - timedelta(days=months * 30)

    keyword_filter = Q()
    for keyword in INTERVIEW_KEYWORDS:
        keyword_filter |= Q(summary__icontains=keyword)

    events = CalendarEvent.objects.filter(
        keyword_filter,
        user=user,
        start_time__gte=cutoff,
        all_day=False,
        status="confirmed",
    ).order_by("start_time")

    total_meetings = 0
    total_minutes = 0
    matching_events = []
    monthly_data = {}

    for event in events:
        duration = event.duration_minutes or 0
        total_meetings += 1
        total_minutes += duration

        matching_events.append({
            "date": event.start_time.strftime("%Y-%m-%d"),
            "summary": event.summary,
            "duration_minutes": duration,
        })

        month_key = event.start_time.strftime("%Y-%m")
        month_label = event.start_time.strftime("%B %Y")

        if month_key not in monthly_data:
            monthly_data[month_key] = {
                "month": month_key,
                "label": month_label,
                "meeting_count": 0,
                "total_minutes": 0,
            }

        monthly_data[month_key]["meeting_count"] += 1
        monthly_data[month_key]["total_minutes"] += duration

    monthly_breakdown = sorted(
        monthly_data.values(),
        key=lambda x: x["month"],
    )

    return {
        "total_meetings": total_meetings,
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 2),
        "monthly_breakdown": monthly_breakdown,
        "matching_events": matching_events,
    }
