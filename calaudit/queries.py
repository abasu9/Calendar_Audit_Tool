"""
Audit query functions for calendar metrics.

This module contains database queries that calculate various audit metrics
from the synced calendar events. Each function returns data suitable for
API responses.

OVERVIEW OF FUNCTIONS:
----------------------
1. get_monthly_meeting_time()  - Total hours spent in meetings per month
2. get_meeting_extremes()      - Month with most/least number of meetings
3. classify_week()             - Helper to classify a week as busy/relaxed/normal
4. get_weekly_extremes()       - Busiest and most relaxed weeks
5. get_weekly_averages()       - Average meetings and time per week
6. get_top_contacts()          - People you meet with most frequently
7. get_interview_time()        - Time spent in recruiting/interview meetings

DATA SOURCE:
------------
All functions query the CalendarEvent model which stores synced Google Calendar
events. Events have fields like:
- summary (title)
- start_time, end_time
- duration_minutes
- all_day (boolean)
- status (confirmed, tentative, cancelled)
- raw_json (full Google API response including attendees)
"""

from datetime import timedelta
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

from calsync.models import CalendarEvent


def get_monthly_meeting_time(months: int = 3) -> list[dict]:
    """
    Calculate total meeting time per month for the last N months.
    
    PURPOSE:
    --------
    Answers the question: "How much time am I spending in meetings each month?"
    This helps identify trends in meeting load over time.
    
    PARAMETERS:
    -----------
    - months: Number of months to look back (default 3)
    
    RETURNS:
    --------
    List of dicts, one per month with meetings, containing:
    - month: "YYYY-MM" format (e.g., "2026-07")
    - label: Human readable (e.g., "July 2026")
    - total_minutes: Sum of all meeting durations
    - total_hours: Same value converted to hours (rounded to 2 decimals)
    
    HOW IT WORKS:
    -------------
    1. Calculate a cutoff date (N months ago from today)
    2. Query CalendarEvent filtering:
       - start_time >= cutoff (only events in our time window)
       - all_day = False (exclude all-day events - they have no duration)
       - status = "confirmed" (exclude tentative/cancelled meetings)
    3. Use Django's TruncMonth to group events by their start month
    4. Aggregate using Sum("duration_minutes") to total time per month
    5. Order by month ascending (oldest first)
    6. Format each row with human-readable labels
    
    DATABASE QUERY (equivalent SQL):
    --------------------------------
    SELECT 
        DATE_TRUNC('month', start_time) as month,
        SUM(duration_minutes) as total_minutes
    FROM calsync_calendarevent
    WHERE start_time >= cutoff
      AND all_day = FALSE
      AND status = 'confirmed'
    GROUP BY DATE_TRUNC('month', start_time)
    ORDER BY month;
    
    EXAMPLE RETURN:
    ---------------
    [
        {"month": "2026-06", "label": "June 2026", "total_minutes": 480, "total_hours": 8.0},
        {"month": "2026-07", "label": "July 2026", "total_minutes": 750, "total_hours": 12.5},
    ]
    """
    # Step 1: Calculate cutoff date (N months ago)
    # Using 30 days per month as approximation
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Step 2-5: Query database with grouping and aggregation
    queryset = (
        CalendarEvent.objects
        .filter(
            start_time__gte=cutoff,
            all_day=False,           # Exclude all-day events
            status="confirmed",      # Only confirmed meetings
        )
        .annotate(month=TruncMonth("start_time"))  # Group by month
        .values("month")                            # Select only month
        .annotate(total_minutes=Sum("duration_minutes"))  # Sum durations
        .order_by("month")                          # Sort chronologically
    )
    
    # Step 6: Format results with human-readable labels
    results = []
    for row in queryset:
        month_date = row["month"]
        total_minutes = row["total_minutes"] or 0  # Handle None
        
        results.append({
            "month": month_date.strftime("%Y-%m"),      # "2026-07"
            "label": month_date.strftime("%B %Y"),      # "July 2026"
            "total_minutes": total_minutes,
            "total_hours": round(total_minutes / 60, 2),
        })
    
    return results


def get_meeting_extremes(months: int = 3) -> dict:
    """
    Find the month with the most and least meetings.
    
    PURPOSE:
    --------
    Answers the question: "Which month had the highest/lowest number of meetings?"
    This helps identify busy periods and lighter months.
    
    PARAMETERS:
    -----------
    - months: Number of months to look back (default 3)
    
    RETURNS:
    --------
    Dict containing:
    - highest: The month with most meetings (or None if no data)
    - lowest: The month with fewest meetings (or None if no data)
    - all_months: List of all months with their meeting counts
    
    HOW IT WORKS:
    -------------
    1. Calculate cutoff date (N months ago)
    2. Query CalendarEvent filtering same as get_monthly_meeting_time()
    3. Group by month using TruncMonth
    4. Count meetings per month using Count("google_event_id")
    5. Format results with month labels
    6. Find max/min using Python's max()/min() with key function
    
    DATABASE QUERY (equivalent SQL):
    --------------------------------
    SELECT 
        DATE_TRUNC('month', start_time) as month,
        COUNT(google_event_id) as meeting_count
    FROM calsync_calendarevent
    WHERE start_time >= cutoff
      AND all_day = FALSE
      AND status = 'confirmed'
    GROUP BY DATE_TRUNC('month', start_time)
    ORDER BY month;
    
    EXAMPLE RETURN:
    ---------------
    {
        "highest": {"month": "2026-07", "label": "July 2026", "meeting_count": 15},
        "lowest": {"month": "2026-09", "label": "September 2026", "meeting_count": 3},
        "all_months": [...]
    }
    """
    # Step 1: Calculate cutoff date (N months ago)
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Step 2-4: Query with grouping and counting
    queryset = (
        CalendarEvent.objects
        .filter(
            start_time__gte=cutoff,
            all_day=False,           # Exclude all-day events
            status="confirmed",      # Only confirmed meetings
        )
        .annotate(month=TruncMonth("start_time"))  # Group by month
        .values("month")                            # Select only month
        .annotate(meeting_count=Count("google_event_id"))  # Count meetings
        .order_by("month")                          # Sort chronologically
    )
    
    # Step 5: Format results with human-readable labels
    all_months = []
    for row in queryset:
        month_date = row["month"]
        meeting_count = row["meeting_count"] or 0
        
        all_months.append({
            "month": month_date.strftime("%Y-%m"),      # "2026-07"
            "label": month_date.strftime("%B %Y"),      # "July 2026"
            "meeting_count": meeting_count,
        })
    
    # Step 6: Find highest and lowest using Python max/min
    if all_months:
        # max() finds the dict with highest meeting_count
        highest = max(all_months, key=lambda x: x["meeting_count"])
        # min() finds the dict with lowest meeting_count
        lowest = min(all_months, key=lambda x: x["meeting_count"])
    else:
        highest = None
        lowest = None
    
    return {
        "highest": highest,
        "lowest": lowest,
        "all_months": all_months,
    }


# =============================================================================
# WEEK CLASSIFICATION CONSTANTS
# =============================================================================
# These thresholds determine how weeks are labeled in the UI
# Adjust these values to change sensitivity of busy/relaxed classification

BUSY_THRESHOLD_MINUTES = 300      # More than 5 hours = busy week
RELAXED_THRESHOLD_MINUTES = 120   # Less than 2 hours = relaxed week


def classify_week(total_minutes: int) -> str:
    """
    Classify a week based on total meeting time.
    
    PURPOSE:
    --------
    Helper function to categorize weeks for visual display in the dashboard.
    
    PARAMETERS:
    -----------
    - total_minutes: Total meeting time for the week
    
    RETURNS:
    --------
    One of: "busy", "relaxed", or "normal"
    
    THRESHOLDS:
    -----------
    - Busy: > 5 hours (300 minutes) - You spent a lot of time in meetings
    - Relaxed: < 2 hours (120 minutes) - Light meeting load
    - Normal: 2-5 hours - Average meeting load
    
    HOW IT WORKS:
    -------------
    Simple comparison against threshold constants defined above.
    The UI uses this to color-code weeks (red for busy, green for relaxed).
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
    
    PURPOSE:
    --------
    Answers the question: "Which week was I busiest/least busy?"
    Helps identify patterns of intense meeting periods vs lighter weeks.
    
    PARAMETERS:
    -----------
    - months: Number of months to look back (default 3)
    
    RETURNS:
    --------
    Dict containing:
    - threshold: The classification thresholds being used
    - busiest: Week with most meeting time (or None)
    - most_relaxed: Week with least meeting time (or None)
    - all_weeks: List of all weeks with their data
    
    HOW IT WORKS:
    -------------
    1. Calculate cutoff date (N months ago)
    2. Query CalendarEvent with same filters (no all-day, confirmed only)
    3. Group by ISO week using TruncWeek (weeks start on Monday)
    4. For each week, count meetings AND sum total duration
    5. Calculate week end date (start + 6 days)
    6. Classify each week as busy/relaxed/normal using classify_week()
    7. Find extremes using max()/min() on total_minutes
    
    ISO WEEK FORMAT:
    ----------------
    Weeks are identified using ISO 8601 format: YYYY-Www
    Example: "2026-W27" = 27th week of 2026
    - Weeks start on Monday
    - Week 1 is the week containing the first Thursday of the year
    
    DATABASE QUERY (equivalent SQL):
    --------------------------------
    SELECT 
        DATE_TRUNC('week', start_time) as week,
        COUNT(google_event_id) as meeting_count,
        SUM(duration_minutes) as total_minutes
    FROM calsync_calendarevent
    WHERE start_time >= cutoff
      AND all_day = FALSE
      AND status = 'confirmed'
    GROUP BY DATE_TRUNC('week', start_time)
    ORDER BY week;
    
    EXAMPLE RETURN:
    ---------------
    {
        "threshold": {"busy_minutes": 300, "relaxed_minutes": 120},
        "busiest": {"week": "2026-W27", "meeting_count": 8, "total_minutes": 420, ...},
        "most_relaxed": {"week": "2026-W35", "meeting_count": 1, "total_minutes": 30, ...},
        "all_weeks": [...]
    }
    """
    # Step 1: Calculate cutoff date
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Step 2-4: Query with weekly grouping and dual aggregation
    queryset = (
        CalendarEvent.objects
        .filter(
            start_time__gte=cutoff,
            all_day=False,           # Exclude all-day events
            status="confirmed",      # Only confirmed meetings
        )
        .annotate(week=TruncWeek("start_time"))  # Group by ISO week
        .values("week")
        .annotate(
            meeting_count=Count("google_event_id"),  # Count meetings
            total_minutes=Sum("duration_minutes"),    # Sum durations
        )
        .order_by("week")
    )
    
    # Step 5-6: Format results with all computed fields
    all_weeks = []
    for row in queryset:
        week_start = row["week"]
        meeting_count = row["meeting_count"] or 0
        total_minutes = row["total_minutes"] or 0
        
        # Calculate week end (Monday + 6 days = Sunday)
        week_end = week_start + timedelta(days=6)
        
        # ISO week format: %G = ISO year, %V = ISO week number
        iso_week = week_start.strftime("%G-W%V")
        
        all_weeks.append({
            "week": iso_week,                              # "2026-W27"
            "start_date": week_start.strftime("%Y-%m-%d"), # "2026-07-06"
            "end_date": week_end.strftime("%Y-%m-%d"),     # "2026-07-12"
            "meeting_count": meeting_count,
            "total_minutes": total_minutes,
            "total_hours": round(total_minutes / 60, 2),
            "classification": classify_week(total_minutes), # "busy"/"relaxed"/"normal"
        })
    
    # Step 7: Find extremes (busiest = max minutes, most relaxed = min minutes)
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
    
    PURPOSE:
    --------
    Answers the question: "On average, how many meetings do I have per week
    and how much time do they take?"
    This establishes a baseline to understand if specific weeks are above
    or below your typical workload.
    
    PARAMETERS:
    -----------
    - months: Number of months to look back (default 3)
    
    RETURNS:
    --------
    Dict containing:
    - weeks_analyzed: Number of weeks with at least one meeting
    - average_meetings_per_week: Mean meeting count
    - average_minutes_per_week: Mean total duration
    - average_hours_per_week: Same as above but in hours
    - weekly_data: Raw data for each week
    
    HOW IT WORKS:
    -------------
    1. Calculate cutoff date (N months ago)
    2. Query CalendarEvent grouped by ISO week (same as get_weekly_extremes)
    3. For each week, collect meeting count and total minutes
    4. Keep running totals of meetings and minutes across all weeks
    5. Calculate averages: total / number_of_weeks
    6. Handle edge case of no data (return 0 for all averages)
    
    IMPORTANT NOTE:
    ---------------
    Only weeks WITH meetings are counted. If you had zero meetings
    in a week, that week won't appear in weekly_data and won't be
    counted in weeks_analyzed. This means averages are calculated
    only over active meeting weeks, not calendar weeks.
    
    CALCULATION:
    ------------
    average_meetings_per_week = sum(all meeting counts) / number of weeks
    average_minutes_per_week = sum(all durations) / number of weeks
    average_hours_per_week = average_minutes_per_week / 60
    
    EXAMPLE RETURN:
    ---------------
    {
        "weeks_analyzed": 12,
        "average_meetings_per_week": 4.5,
        "average_minutes_per_week": 180.0,
        "average_hours_per_week": 3.0,
        "weekly_data": [
            {"week": "2026-W25", "start_date": "2026-06-15", "meeting_count": 3, "total_minutes": 120},
            ...
        ]
    }
    """
    # Step 1: Calculate cutoff date
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Step 2: Query with weekly grouping
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
    
    # Step 3-4: Format weekly data and calculate running totals
    weekly_data = []
    total_meetings = 0
    total_minutes = 0
    
    for row in queryset:
        week_start = row["week"]
        meeting_count = row["meeting_count"] or 0
        minutes = row["total_minutes"] or 0
        
        # ISO week format
        iso_week = week_start.strftime("%G-W%V")
        
        weekly_data.append({
            "week": iso_week,
            "start_date": week_start.strftime("%Y-%m-%d"),
            "meeting_count": meeting_count,
            "total_minutes": minutes,
        })
        
        # Running totals for average calculation
        total_meetings += meeting_count
        total_minutes += minutes
    
    # Step 5-6: Calculate averages
    weeks_analyzed = len(weekly_data)
    
    if weeks_analyzed > 0:
        avg_meetings = round(total_meetings / weeks_analyzed, 2)
        avg_minutes = round(total_minutes / weeks_analyzed, 2)
        avg_hours = round(avg_minutes / 60, 2)
    else:
        # Edge case: no meetings at all
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
    
    PURPOSE:
    --------
    Answers the question: "Who do I meet with most frequently?"
    Helps identify key collaborators, stakeholders, or meeting partners.
    
    PARAMETERS:
    -----------
    - months: Number of months to look back (default 3)
    - limit: Number of top contacts to return (default 3)
    
    RETURNS:
    --------
    Dict containing:
    - top_contacts: Limited list of top N contacts
    - all_contacts: Full sorted list of everyone you've met with
    
    Each contact has: email, name, meeting_count, total_minutes, total_hours
    
    HOW IT WORKS:
    -------------
    1. Query all events in the time range (no grouping in DB)
    2. Loop through each event in Python
    3. For each event, extract the "attendees" array from raw_json
       (raw_json stores the full Google Calendar API response)
    4. For each attendee:
       - Skip if no email
       - Skip if attendee.self == True (that's you!)
       - Add to running totals: increment meeting_count, add duration
       - Capture displayName if available
    5. Convert the dict to a list and sort by meeting_count (desc)
    6. Slice to get top N
    
    WHY NOT USE DATABASE AGGREGATION?
    ---------------------------------
    Attendee data is stored in a JSONField (raw_json), not as separate
    rows or a many-to-many relationship. We can't efficiently query
    "attendees" array in Postgres JSON, so we iterate in Python.
    
    For large datasets, this could be optimized by:
    - Creating a separate Attendee model
    - Using Postgres JSONB operators (but complex)
    
    GOOGLE CALENDAR ATTENDEE FORMAT:
    --------------------------------
    {
        "attendees": [
            {
                "email": "alice@example.com",
                "displayName": "Alice Smith",
                "responseStatus": "accepted",
                "self": false,
                "organizer": false
            },
            ...
        ]
    }
    
    The "self" field indicates the calendar owner. We skip this person
    since you don't want to see yourself in your top contacts!
    
    EXAMPLE RETURN:
    ---------------
    {
        "top_contacts": [
            {"email": "alice@example.com", "name": "Alice Smith", "meeting_count": 12, 
             "total_minutes": 720, "total_hours": 12.0},
            ...
        ],
        "all_contacts": [...]
    }
    """
    from collections import defaultdict
    
    # Step 1: Calculate cutoff and query events
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    events = CalendarEvent.objects.filter(
        start_time__gte=cutoff,
        all_day=False,           # Exclude all-day events
        status="confirmed",      # Only confirmed meetings
    )
    
    # Step 2-4: Aggregate contacts from all events
    # Using defaultdict for automatic initialization of new contacts
    contacts = defaultdict(lambda: {"name": "", "meeting_count": 0, "total_minutes": 0})
    
    for event in events:
        raw_json = event.raw_json or {}
        attendees = raw_json.get("attendees", [])
        duration = event.duration_minutes or 0
        
        for attendee in attendees:
            email = attendee.get("email", "")
            if not email:
                continue
            
            # Skip self (the calendar owner)
            # Google marks your own entry with "self": true
            if attendee.get("self", False):
                continue
            
            # Skip organizer if they're also marked as self
            # (edge case: sometimes both flags are set)
            if attendee.get("organizer", False) and attendee.get("self", False):
                continue
            
            # Increment meeting count and add duration for this contact
            contacts[email]["meeting_count"] += 1
            contacts[email]["total_minutes"] += duration
            
            # Capture display name if available
            # Only store if we don't have one yet (first meeting wins)
            display_name = attendee.get("displayName", "")
            if display_name and not contacts[email]["name"]:
                contacts[email]["name"] = display_name
    
    # Step 5: Convert dict to sorted list
    all_contacts = [
        {
            "email": email,
            "name": data["name"],
            "meeting_count": data["meeting_count"],
            "total_minutes": data["total_minutes"],
            "total_hours": round(data["total_minutes"] / 60, 2),
        }
        for email, data in contacts.items()
    ]
    
    # Sort by meeting_count (descending), then by total_minutes (descending)
    # The negative sign reverses the sort (highest first)
    all_contacts.sort(key=lambda x: (-x["meeting_count"], -x["total_minutes"]))
    
    # Step 6: Slice to get top N
    top_contacts = all_contacts[:limit]
    
    return {
        "top_contacts": top_contacts,
        "all_contacts": all_contacts,
    }


# =============================================================================
# INTERVIEW/RECRUITING DETECTION
# =============================================================================
# Keywords that identify interview/recruiting events
# These are matched case-insensitively against event summaries
# Add more keywords here to improve detection accuracy

INTERVIEW_KEYWORDS = [
    "interview",      # Most common: "Interview with John"
    "candidate",      # "Candidate: Jane Doe"
    "recruiting",     # "Recruiting sync"
    "recruitment",    # "Recruitment planning"
    "phone screen",   # "Phone Screen - Engineer"
    "screening",      # "Screening call"
    "hiring",         # "Hiring committee"
]


def get_interview_time(months: int = 3) -> dict:
    """
    Calculate time spent in recruiting/interview meetings.
    
    PURPOSE:
    --------
    Answers the question: "How much time am I spending on recruiting?"
    This is useful for managers and interviewers to track their
    recruiting load separately from regular meetings.
    
    PARAMETERS:
    -----------
    - months: Number of months to look back (default 3)
    
    RETURNS:
    --------
    Dict containing:
    - total_meetings: Count of matching events
    - total_minutes: Sum of durations
    - total_hours: Same as above in hours
    - monthly_breakdown: Grouped by month for trends
    - matching_events: List of all matched events with details
    
    HOW IT WORKS:
    -------------
    1. Build a compound OR filter using Django Q objects
       - Q(summary__icontains="interview") | Q(summary__icontains="candidate") | ...
       - __icontains does case-insensitive substring matching
    2. Query events that match ANY keyword (OR logic)
    3. Loop through results in Python to:
       - Sum up totals
       - Build list of matching events
       - Group by month for the breakdown
    
    WHY KEYWORD MATCHING?
    ---------------------
    Interview events aren't specially tagged in Google Calendar.
    We identify them by looking for common words in the title.
    This is imperfect but works well for most calendaring conventions.
    
    FALSE POSITIVES:
    ----------------
    Events like "Interview prep" or "Post-interview debrief" will match.
    This is usually desirable as they're recruiting-related.
    
    FALSE NEGATIVES:
    ----------------
    Events with unusual naming like "Chat with potential hire" won't match.
    Add more keywords to INTERVIEW_KEYWORDS to improve coverage.
    
    DATABASE QUERY (equivalent SQL):
    --------------------------------
    SELECT *
    FROM calsync_calendarevent
    WHERE start_time >= cutoff
      AND all_day = FALSE
      AND status = 'confirmed'
      AND (
        LOWER(summary) LIKE '%interview%'
        OR LOWER(summary) LIKE '%candidate%'
        OR LOWER(summary) LIKE '%recruiting%'
        -- ... etc for all keywords
      )
    ORDER BY start_time;
    
    EXAMPLE RETURN:
    ---------------
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
    
    # Step 1: Calculate cutoff date
    cutoff = timezone.now() - timedelta(days=months * 30)
    
    # Step 2: Build compound OR filter for keywords
    # Start with empty Q object and OR (|=) each keyword filter
    keyword_filter = Q()
    for keyword in INTERVIEW_KEYWORDS:
        # __icontains = case-insensitive substring match
        # "Interview" matches "interview", "INTERVIEW", "Interview", etc.
        keyword_filter |= Q(summary__icontains=keyword)
    
    # Step 3: Query matching events
    events = CalendarEvent.objects.filter(
        keyword_filter,              # Must match at least one keyword
        start_time__gte=cutoff,      # Within time range
        all_day=False,               # Exclude all-day events
        status="confirmed",          # Only confirmed meetings
    ).order_by("start_time")         # Chronological order
    
    # Step 4: Process results in Python
    total_meetings = 0
    total_minutes = 0
    matching_events = []
    monthly_data = {}  # {month_str: {"meeting_count": N, "total_minutes": M, ...}}
    
    for event in events:
        duration = event.duration_minutes or 0
        total_meetings += 1
        total_minutes += duration
        
        # Build list of matching events for display
        matching_events.append({
            "date": event.start_time.strftime("%Y-%m-%d"),
            "summary": event.summary,
            "duration_minutes": duration,
        })
        
        # Group by month for breakdown
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
    
    # Convert monthly dict to sorted list
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
