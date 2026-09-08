"""
Audit query functions for calendar metrics.

This module contains database queries that calculate various audit metrics
from the synced calendar events. Each function returns data suitable for
API responses.
"""

from datetime import timedelta
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

from calsync.models import CalendarEvent


def get_monthly_meeting_time(months: int = 3) -> list[dict]:
    """
    Calculate total meeting time per month for the last N months.
    
    PARAMETERS:
    - months: Number of months to look back (default 3)
    
    RETURNS:
    - List of dicts with month, label, total_minutes, total_hours
    
    EXCLUDES:
    - All-day events (they don't have meaningful duration)
    - Non-confirmed meetings (tentative, cancelled)
    
    EXAMPLE RETURN:
    [
        {"month": "2026-06", "label": "June 2026", "total_minutes": 480, "total_hours": 8.0},
        {"month": "2026-07", "label": "July 2026", "total_minutes": 750, "total_hours": 12.5},
    ]
    """
    # Calculate cutoff date (N months ago)
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Query: group by month, sum duration
    queryset = (
        CalendarEvent.objects
        .filter(
            start_time__gte=cutoff,
            all_day=False,           # Exclude all-day events
            status="confirmed",      # Only confirmed meetings
        )
        .annotate(month=TruncMonth("start_time"))
        .values("month")
        .annotate(total_minutes=Sum("duration_minutes"))
        .order_by("month")
    )
    
    # Format results with human-readable labels
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


def get_meeting_extremes(months: int = 3) -> dict:
    """
    Find the month with the most and least meetings.
    
    PARAMETERS:
    - months: Number of months to look back (default 3)
    
    RETURNS:
    - Dict with highest, lowest, and all_months data
    
    EXCLUDES:
    - All-day events (they don't count as meetings)
    - Non-confirmed meetings (tentative, cancelled)
    
    EXAMPLE RETURN:
    {
        "highest": {"month": "2026-07", "label": "July 2026", "meeting_count": 15},
        "lowest": {"month": "2026-09", "label": "September 2026", "meeting_count": 3},
        "all_months": [...]
    }
    """
    # Calculate cutoff date (N months ago)
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Query: group by month, count meetings
    queryset = (
        CalendarEvent.objects
        .filter(
            start_time__gte=cutoff,
            all_day=False,           # Exclude all-day events
            status="confirmed",      # Only confirmed meetings
        )
        .annotate(month=TruncMonth("start_time"))
        .values("month")
        .annotate(meeting_count=Count("google_event_id"))
        .order_by("month")
    )
    
    # Format results with human-readable labels
    all_months = []
    for row in queryset:
        month_date = row["month"]
        meeting_count = row["meeting_count"] or 0
        
        all_months.append({
            "month": month_date.strftime("%Y-%m"),
            "label": month_date.strftime("%B %Y"),
            "meeting_count": meeting_count,
        })
    
    # Find highest and lowest
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


# Thresholds for classifying weeks (in minutes)
BUSY_THRESHOLD_MINUTES = 300      # More than 5 hours = busy
RELAXED_THRESHOLD_MINUTES = 120   # Less than 2 hours = relaxed


def classify_week(total_minutes: int) -> str:
    """
    Classify a week based on total meeting time.
    
    THRESHOLDS:
    - Busy: > 5 hours (300 minutes)
    - Relaxed: < 2 hours (120 minutes)
    - Normal: 2-5 hours
    """
    if total_minutes > BUSY_THRESHOLD_MINUTES:
        return "busy"
    elif total_minutes < RELAXED_THRESHOLD_MINUTES:
        return "relaxed"
    else:
        return "normal"


def get_weekly_extremes(months: int = 3) -> dict:
    """
    Find the busiest and most relaxed weeks.
    
    PARAMETERS:
    - months: Number of months to look back (default 3)
    
    RETURNS:
    - Dict with busiest, most_relaxed, threshold info, and all_weeks data
    
    EXCLUDES:
    - All-day events (they don't count as meetings)
    - Non-confirmed meetings (tentative, cancelled)
    
    CLASSIFICATION:
    - Busy: > 5 hours (300 minutes) of meetings
    - Relaxed: < 2 hours (120 minutes) of meetings
    - Normal: 2-5 hours
    
    EXAMPLE RETURN:
    {
        "threshold": {"busy_minutes": 300, "relaxed_minutes": 120},
        "busiest": {"week": "2026-W27", "meeting_count": 8, "total_minutes": 420, ...},
        "most_relaxed": {"week": "2026-W35", "meeting_count": 1, "total_minutes": 30, ...},
        "all_weeks": [...]
    }
    """
    # Calculate cutoff date (N months ago)
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Query: group by ISO week, count meetings and sum duration
    queryset = (
        CalendarEvent.objects
        .filter(
            start_time__gte=cutoff,
            all_day=False,           # Exclude all-day events
            status="confirmed",      # Only confirmed meetings
        )
        .annotate(week=TruncWeek("start_time"))
        .values("week")
        .annotate(
            meeting_count=Count("google_event_id"),
            total_minutes=Sum("duration_minutes"),
        )
        .order_by("week")
    )
    
    # Format results
    all_weeks = []
    for row in queryset:
        week_start = row["week"]
        meeting_count = row["meeting_count"] or 0
        total_minutes = row["total_minutes"] or 0
        
        # Calculate week end (6 days after start)
        week_end = week_start + timedelta(days=6)
        
        # ISO week format: YYYY-Www
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
    
    # Find busiest (max minutes) and most relaxed (min minutes)
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


def get_weekly_averages(months: int = 3) -> dict:
    """
    Calculate average number of meetings and time per week.
    
    PARAMETERS:
    - months: Number of months to look back (default 3)
    
    RETURNS:
    - Dict with average meetings per week, average minutes/hours per week,
      and the raw weekly data
    
    EXCLUDES:
    - All-day events (they don't count as meetings)
    - Non-confirmed meetings (tentative, cancelled)
    
    EXAMPLE RETURN:
    {
        "weeks_analyzed": 12,
        "average_meetings_per_week": 4.5,
        "average_minutes_per_week": 180.0,
        "average_hours_per_week": 3.0,
        "weekly_data": [...]
    }
    """
    # Calculate cutoff date (N months ago)
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Query: group by ISO week, count meetings and sum duration
    queryset = (
        CalendarEvent.objects
        .filter(
            start_time__gte=cutoff,
            all_day=False,           # Exclude all-day events
            status="confirmed",      # Only confirmed meetings
        )
        .annotate(week=TruncWeek("start_time"))
        .values("week")
        .annotate(
            meeting_count=Count("google_event_id"),
            total_minutes=Sum("duration_minutes"),
        )
        .order_by("week")
    )
    
    # Format weekly data
    weekly_data = []
    total_meetings = 0
    total_minutes = 0
    
    for row in queryset:
        week_start = row["week"]
        meeting_count = row["meeting_count"] or 0
        minutes = row["total_minutes"] or 0
        
        # ISO week format: YYYY-Www
        iso_week = week_start.strftime("%G-W%V")
        
        weekly_data.append({
            "week": iso_week,
            "start_date": week_start.strftime("%Y-%m-%d"),
            "meeting_count": meeting_count,
            "total_minutes": minutes,
        })
        
        total_meetings += meeting_count
        total_minutes += minutes
    
    # Calculate averages
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


def get_top_contacts(months: int = 3, limit: int = 3) -> dict:
    """
    Find the people you have the most meetings with.
    
    PARAMETERS:
    - months: Number of months to look back (default 3)
    - limit: Number of top contacts to return (default 3)
    
    RETURNS:
    - Dict with top_contacts (limited) and all_contacts (full list)
    
    HOW IT WORKS:
    1. Query all events in the time range
    2. For each event, extract attendees from raw_json
    3. Aggregate by email: count meetings, sum duration
    4. Exclude self (organizer marked with "self": true)
    5. Sort by meeting_count descending
    
    EXAMPLE RETURN:
    {
        "top_contacts": [
            {"email": "alice@example.com", "meeting_count": 12, "total_minutes": 720},
            ...
        ],
        "all_contacts": [...]
    }
    """
    from collections import defaultdict
    
    # Calculate cutoff date (N months ago)
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Query all events in the time range
    events = CalendarEvent.objects.filter(
        start_time__gte=cutoff,
        all_day=False,           # Exclude all-day events
        status="confirmed",      # Only confirmed meetings
    )
    
    # Aggregate contacts: {email: {"meeting_count": N, "total_minutes": M}}
    contacts = defaultdict(lambda: {"meeting_count": 0, "total_minutes": 0})
    
    for event in events:
        raw_json = event.raw_json or {}
        attendees = raw_json.get("attendees", [])
        duration = event.duration_minutes or 0
        
        for attendee in attendees:
            email = attendee.get("email", "")
            if not email:
                continue
            
            # Skip self (the calendar owner)
            if attendee.get("self", False):
                continue
            
            # Skip organizer if they're also marked in attendees
            # (sometimes the organizer is listed as an attendee)
            if attendee.get("organizer", False) and attendee.get("self", False):
                continue
            
            contacts[email]["meeting_count"] += 1
            contacts[email]["total_minutes"] += duration
    
    # Convert to list and sort by meeting_count descending
    all_contacts = [
        {
            "email": email,
            "meeting_count": data["meeting_count"],
            "total_minutes": data["total_minutes"],
            "total_hours": round(data["total_minutes"] / 60, 2),
        }
        for email, data in contacts.items()
    ]
    
    # Sort by meeting_count (primary), then by total_minutes (secondary)
    all_contacts.sort(key=lambda x: (-x["meeting_count"], -x["total_minutes"]))
    
    # Get top N contacts
    top_contacts = all_contacts[:limit]
    
    return {
        "top_contacts": top_contacts,
        "all_contacts": all_contacts,
    }


# Keywords that identify interview/recruiting events
# These are matched case-insensitively against event summaries
INTERVIEW_KEYWORDS = [
    "interview",
    "candidate",
    "recruiting",
    "recruitment",
    "phone screen",
    "screening",
    "hiring",
]


def get_interview_time(months: int = 3) -> dict:
    """
    Calculate time spent in recruiting/interview meetings.
    
    PARAMETERS:
    - months: Number of months to look back (default 3)
    
    RETURNS:
    - Dict with total stats, monthly breakdown, and matching events
    
    HOW IT WORKS:
    1. Build Q objects for case-insensitive keyword matching on summary
    2. Query all matching events in the time range
    3. Calculate totals and group by month
    
    KEYWORDS MATCHED (case-insensitive):
    - interview, candidate, recruiting, recruitment
    - phone screen, screening, hiring
    
    EXAMPLE RETURN:
    {
        "total_meetings": 5,
        "total_minutes": 300,
        "total_hours": 5.0,
        "monthly_breakdown": [
            {"month": "2026-07", "label": "July 2026", "meeting_count": 2, "total_minutes": 120}
        ],
        "matching_events": [
            {"date": "2026-07-15", "summary": "Interview - John Doe", "duration_minutes": 60}
        ]
    }
    """
    from django.db.models import Q
    
    # Calculate cutoff date (N months ago)
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Build Q objects for case-insensitive keyword matching
    # Each keyword becomes summary__icontains=keyword
    keyword_filter = Q()
    for keyword in INTERVIEW_KEYWORDS:
        keyword_filter |= Q(summary__icontains=keyword)
    
    # Query matching events
    events = CalendarEvent.objects.filter(
        keyword_filter,
        start_time__gte=cutoff,
        all_day=False,           # Exclude all-day events
        status="confirmed",      # Only confirmed meetings
    ).order_by("start_time")
    
    # Calculate totals
    total_meetings = 0
    total_minutes = 0
    matching_events = []
    monthly_data = {}  # {month_str: {"meeting_count": N, "total_minutes": M, "label": "..."}}
    
    for event in events:
        duration = event.duration_minutes or 0
        total_meetings += 1
        total_minutes += duration
        
        # Add to matching events list
        matching_events.append({
            "date": event.start_time.strftime("%Y-%m-%d"),
            "summary": event.summary,
            "duration_minutes": duration,
        })
        
        # Group by month
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
    
    # Convert monthly data to sorted list
    monthly_breakdown = sorted(
        monthly_data.values(),
        key=lambda x: x["month"]
    )
    
    return {
        "total_meetings": total_meetings,
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 2),
        "monthly_breakdown": monthly_breakdown,
        "matching_events": matching_events,
    }
