"""
Audit API views.

This module contains DRF API views for calendar audit metrics.
Each view corresponds to a specific metric endpoint.
"""

from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .queries import (
    get_interview_time,
    get_meeting_extremes,
    get_monthly_meeting_time,
    get_top_contacts,
    get_weekly_averages,
    get_weekly_extremes,
)


def dashboard(request):
    """
    Render the audit dashboard page.
    
    This view serves the HTML template that displays all 6 audit metrics.
    The template uses JavaScript to fetch data from the API endpoints.
    
    URL: /api/audit/
    """
    return render(request, "calaudit/dashboard.html")


class MonthlyMeetingTimeView(APIView):
    """
    API endpoint for total meeting time per month.
    
    GET /api/audit/monthly-time/
    
    Returns the total time spent in meetings for each month
    over the last 3 months.
    
    RESPONSE FORMAT:
    {
        "metric": "monthly_meeting_time",
        "period": "last_3_months",
        "data": [
            {"month": "2026-06", "label": "June 2026", "total_minutes": 480, "total_hours": 8.0},
            ...
        ]
    }
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Handle GET request for monthly meeting time.
        
        Query Parameters:
        - months: Number of months to look back (default: 3)
        """
        # Get optional months parameter (default 3)
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))  # Clamp between 1 and 12
        except (ValueError, TypeError):
            months = 3
        
        # Fetch the data
        data = get_monthly_meeting_time(months=months)
        
        return Response({
            "metric": "monthly_meeting_time",
            "period": f"last_{months}_months",
            "data": data,
        })


class MeetingExtremesView(APIView):
    """
    API endpoint for month with most/least meetings.
    
    GET /api/audit/meeting-extremes/
    
    Returns the month with the highest and lowest number of meetings
    over the last 3 months.
    
    RESPONSE FORMAT:
    {
        "metric": "meeting_extremes",
        "period": "last_3_months",
        "highest": {"month": "2026-07", "label": "July 2026", "meeting_count": 15},
        "lowest": {"month": "2026-09", "label": "September 2026", "meeting_count": 3},
        "all_months": [...]
    }
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Handle GET request for meeting extremes.
        
        Query Parameters:
        - months: Number of months to look back (default: 3)
        """
        # Get optional months parameter (default 3)
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))  # Clamp between 1 and 12
        except (ValueError, TypeError):
            months = 3
        
        # Fetch the data
        data = get_meeting_extremes(months=months)
        
        return Response({
            "metric": "meeting_extremes",
            "period": f"last_{months}_months",
            "highest": data["highest"],
            "lowest": data["lowest"],
            "all_months": data["all_months"],
        })


class WeeklyExtremesView(APIView):
    """
    API endpoint for busiest and most relaxed weeks.
    
    GET /api/audit/weekly-extremes/
    
    Returns the busiest and most relaxed weeks based on total meeting time,
    with classification based on thresholds.
    
    THRESHOLDS:
    - Busy: > 5 hours (300 minutes) of meetings
    - Relaxed: < 2 hours (120 minutes) of meetings
    - Normal: 2-5 hours
    
    RESPONSE FORMAT:
    {
        "metric": "weekly_extremes",
        "period": "last_3_months",
        "threshold": {"busy_minutes": 300, "relaxed_minutes": 120},
        "busiest": {"week": "2026-W27", "total_minutes": 420, "classification": "busy", ...},
        "most_relaxed": {"week": "2026-W35", "total_minutes": 30, "classification": "relaxed", ...},
        "all_weeks": [...]
    }
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Handle GET request for weekly extremes.
        
        Query Parameters:
        - months: Number of months to look back (default: 3)
        """
        # Get optional months parameter (default 3)
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))  # Clamp between 1 and 12
        except (ValueError, TypeError):
            months = 3
        
        # Fetch the data
        data = get_weekly_extremes(months=months)
        
        return Response({
            "metric": "weekly_extremes",
            "period": f"last_{months}_months",
            "threshold": data["threshold"],
            "busiest": data["busiest"],
            "most_relaxed": data["most_relaxed"],
            "all_weeks": data["all_weeks"],
        })


class WeeklyAveragesView(APIView):
    """
    API endpoint for average meetings and time per week.
    
    GET /api/audit/weekly-averages/
    
    Returns the average number of meetings and average time spent
    in meetings per week over the specified period.
    
    RESPONSE FORMAT:
    {
        "metric": "weekly_averages",
        "period": "last_3_months",
        "weeks_analyzed": 12,
        "average_meetings_per_week": 4.5,
        "average_minutes_per_week": 180.0,
        "average_hours_per_week": 3.0,
        "weekly_data": [...]
    }
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Handle GET request for weekly averages.
        
        Query Parameters:
        - months: Number of months to look back (default: 3)
        """
        # Get optional months parameter (default 3)
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))  # Clamp between 1 and 12
        except (ValueError, TypeError):
            months = 3
        
        # Fetch the data
        data = get_weekly_averages(months=months)
        
        return Response({
            "metric": "weekly_averages",
            "period": f"last_{months}_months",
            "weeks_analyzed": data["weeks_analyzed"],
            "average_meetings_per_week": data["average_meetings_per_week"],
            "average_minutes_per_week": data["average_minutes_per_week"],
            "average_hours_per_week": data["average_hours_per_week"],
            "weekly_data": data["weekly_data"],
        })


class TopContactsView(APIView):
    """
    API endpoint for top meeting contacts.
    
    GET /api/audit/top-contacts/
    
    Returns the people you have the most meetings with,
    sorted by meeting count.
    
    RESPONSE FORMAT:
    {
        "metric": "top_contacts",
        "period": "last_3_months",
        "top_contacts": [
            {"email": "alice@example.com", "meeting_count": 12, "total_minutes": 720},
            ...
        ],
        "all_contacts": [...]
    }
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Handle GET request for top contacts.
        
        Query Parameters:
        - months: Number of months to look back (default: 3)
        - limit: Number of top contacts to return (default: 3)
        """
        # Get optional months parameter (default 3)
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))  # Clamp between 1 and 12
        except (ValueError, TypeError):
            months = 3
        
        # Get optional limit parameter (default 3)
        limit = request.query_params.get("limit", 3)
        try:
            limit = int(limit)
            limit = max(1, min(limit, 20))  # Clamp between 1 and 20
        except (ValueError, TypeError):
            limit = 3
        
        # Fetch the data
        data = get_top_contacts(months=months, limit=limit)
        
        return Response({
            "metric": "top_contacts",
            "period": f"last_{months}_months",
            "top_contacts": data["top_contacts"],
            "all_contacts": data["all_contacts"],
        })


class InterviewTimeView(APIView):
    """
    API endpoint for time spent in recruiting/interview meetings.
    
    GET /api/audit/interview-time/
    
    Identifies interview meetings by matching keywords in the event title:
    - interview, candidate, recruiting, recruitment
    - phone screen, screening, hiring
    
    RESPONSE FORMAT:
    {
        "metric": "interview_time",
        "period": "last_3_months",
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
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Handle GET request for interview time.
        
        Query Parameters:
        - months: Number of months to look back (default: 3)
        """
        # Get optional months parameter (default 3)
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))  # Clamp between 1 and 12
        except (ValueError, TypeError):
            months = 3
        
        # Fetch the data
        data = get_interview_time(months=months)
        
        return Response({
            "metric": "interview_time",
            "period": f"last_{months}_months",
            "total_meetings": data["total_meetings"],
            "total_minutes": data["total_minutes"],
            "total_hours": data["total_hours"],
            "monthly_breakdown": data["monthly_breakdown"],
            "matching_events": data["matching_events"],
        })
