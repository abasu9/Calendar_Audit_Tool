"""Render the audit dashboard and return each metric as JSON.

The HTML page loads data from these REST views. Query parameters are converted to
safe ranges before the matching calculation in ``calaudit.queries`` is called.

All views require an authenticated user; metrics are filtered to that user's
events so no data leaks between accounts.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .queries import (
    get_interview_time,
    get_meeting_extremes,
    get_monthly_meeting_time,
    get_top_contacts,
    get_weekly_averages,
    get_weekly_extremes,
)


@login_required
def dashboard(request):
    """Render the page that displays all six audit metrics.

    The template contains the layout and JavaScript that requests each JSON metric
    after the page loads.
    """
    return render(request, "calaudit/dashboard.html", {"user_email": request.user.email})


class MonthlyMeetingTimeView(APIView):
    """Serve monthly meeting-time totals to the dashboard."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return monthly totals for a validated one-to-twelve-month period."""
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3

        data = get_monthly_meeting_time(request.user, months=months)

        return Response({
            "metric": "monthly_meeting_time",
            "period": f"last_{months}_months",
            "data": data,
        })


class MeetingExtremesView(APIView):
    """Serve the months with the highest and lowest meeting counts."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return meeting-count extremes for a safe month range."""
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3

        data = get_meeting_extremes(request.user, months=months)

        return Response({
            "metric": "meeting_extremes",
            "period": f"last_{months}_months",
            "highest": data["highest"],
            "lowest": data["lowest"],
            "all_months": data["all_months"],
        })


class WeeklyExtremesView(APIView):
    """Serve the busiest and most relaxed weeks by meeting time."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return weekly extremes for a validated recent period."""
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3

        data = get_weekly_extremes(request.user, months=months)

        return Response({
            "metric": "weekly_extremes",
            "period": f"last_{months}_months",
            "threshold": data["threshold"],
            "busiest": data["busiest"],
            "most_relaxed": data["most_relaxed"],
            "all_weeks": data["all_weeks"],
        })


class WeeklyAveragesView(APIView):
    """Serve average weekly meeting counts and time."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return weekly averages for a validated recent period."""
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3

        data = get_weekly_averages(request.user, months=months)

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
    """Serve contacts ranked by shared meeting frequency."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return ranked contacts using validated period and result limits."""
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

        data = get_top_contacts(request.user, months=months, limit=limit)

        return Response({
            "metric": "top_contacts",
            "period": f"last_{months}_months",
            "top_contacts": data["top_contacts"],
            "all_contacts": data["all_contacts"],
        })


class InterviewTimeView(APIView):
    """Serve totals and details for recruiting-related meetings."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return recruiting time for a validated recent period."""
        months = request.query_params.get("months", 3)
        try:
            months = int(months)
            months = max(1, min(months, 12))
        except (ValueError, TypeError):
            months = 3

        data = get_interview_time(request.user, months=months)

        return Response({
            "metric": "interview_time",
            "period": f"last_{months}_months",
            "total_meetings": data["total_meetings"],
            "total_minutes": data["total_minutes"],
            "total_hours": data["total_hours"],
            "monthly_breakdown": data["monthly_breakdown"],
            "matching_events": data["matching_events"],
        })
