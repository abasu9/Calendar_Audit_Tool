"""
URL configuration for the calaudit app.

All URLs here are mounted under /api/audit/ in the main config.
"""

from django.urls import path

from . import views

app_name = "calaudit"

urlpatterns = [
    # Monthly meeting time metric
    # Full URL: /api/audit/monthly-time/
    path("monthly-time/", views.MonthlyMeetingTimeView.as_view(), name="monthly-time"),
    
    # Meeting extremes (most/least meetings per month)
    # Full URL: /api/audit/meeting-extremes/
    path("meeting-extremes/", views.MeetingExtremesView.as_view(), name="meeting-extremes"),
    
    # Weekly extremes (busiest/most relaxed week)
    # Full URL: /api/audit/weekly-extremes/
    path("weekly-extremes/", views.WeeklyExtremesView.as_view(), name="weekly-extremes"),
    
    # Weekly averages (average meetings and time per week)
    # Full URL: /api/audit/weekly-averages/
    path("weekly-averages/", views.WeeklyAveragesView.as_view(), name="weekly-averages"),
    
    # Top contacts (people you meet with most)
    # Full URL: /api/audit/top-contacts/
    path("top-contacts/", views.TopContactsView.as_view(), name="top-contacts"),
    
    # Interview/recruiting time
    # Full URL: /api/audit/interview-time/
    path("interview-time/", views.InterviewTimeView.as_view(), name="interview-time"),
]
