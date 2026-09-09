"""Render the audit dashboard and return each metric as JSON.

The HTML page loads data from these REST views. Query parameters are converted to
safe ranges before the matching calculation in ``calaudit.queries`` is called.
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
    """Render the page that displays all six audit metrics.

    The template contains the layout and JavaScript that requests each JSON metric
    after the page loads.
    """
    return render(request, "calaudit/dashboard.html")


class MonthlyMeetingTimeView(APIView):
    """Serve monthly meeting-time totals to the dashboard.

    Public GET requests receive a metric name, selected period, and chronological
    monthly data from the audit query layer.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Return monthly totals for a validated one-to-twelve-month period.

        Missing or invalid ``months`` input becomes three; numeric input is clamped
        before the query result is wrapped in a REST response.
        """
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3
        
        data = get_monthly_meeting_time(months=months)
        
        return Response({
            "metric": "monthly_meeting_time",
            "period": f"last_{months}_months",
            "data": data,
        })


class MeetingExtremesView(APIView):
    """Serve the months with the highest and lowest meeting counts.

    Public GET requests receive both extremes plus the full monthly list that
    supports them.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Return meeting-count extremes for a safe month range.

        The optional ``months`` value defaults to three, is clamped from one to
        twelve, and is passed to the audit query before its fields are serialized.
        """
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3
        
        data = get_meeting_extremes(months=months)
        
        return Response({
            "metric": "meeting_extremes",
            "period": f"last_{months}_months",
            "highest": data["highest"],
            "lowest": data["lowest"],
            "all_months": data["all_months"],
        })


class WeeklyExtremesView(APIView):
    """Serve the busiest and most relaxed weeks by meeting time.

    The response includes classification thresholds and complete weekly data so
    the dashboard can explain how both extremes were selected.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Return weekly extremes for a validated recent period.

        Invalid month input becomes three and valid values are limited to one
        through twelve before querying and serializing the result.
        """
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3
        
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
    """Serve average weekly meeting counts and time.

    The response includes calculated averages and their supporting weekly records
    for the selected period.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Return weekly averages for a validated recent period.

        The ``months`` parameter uses a three-month default and one-to-twelve range,
        then the query result is mapped directly to stable response keys.
        """
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3
        
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
    """Serve contacts ranked by shared meeting frequency.

    The response provides both the requested short list and all calculated contacts
    for the chosen report period.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Return ranked contacts using validated period and result limits.

        Months default to three and range from one to twelve. The contact limit also
        defaults to three and ranges from one to twenty before the query runs.
        """
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3
        
        limit = request.query_params.get("limit", 3)
        try:
            limit = int(limit)
            limit = max(1, min(limit, 20))
        except (ValueError, TypeError):
            limit = 3
        
        data = get_top_contacts(months=months, limit=limit)
        
        return Response({
            "metric": "top_contacts",
            "period": f"last_{months}_months",
            "top_contacts": data["top_contacts"],
            "all_contacts": data["all_contacts"],
        })


class InterviewTimeView(APIView):
    """Serve totals and details for recruiting-related meetings.

    The response includes overall time, a monthly breakdown, and every title that
    matched the configured recruiting keywords.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Return recruiting time for a validated recent period.

        The optional month count defaults to three and is limited to one through
        twelve before the audit result is serialized.
        """
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3
        
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
