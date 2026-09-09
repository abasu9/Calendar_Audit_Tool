"""Map ``/api/audit/`` URLs to the dashboard and report views."""

from django.urls import path

from . import views

app_name = "calaudit"

urlpatterns = [
    # Render the HTML report dashboard.
    path("", views.dashboard, name="dashboard"),

    # Return each audit metric as JSON for the dashboard.
    path("monthly-time/", views.MonthlyMeetingTimeView.as_view(), name="monthly-time"),
    path("meeting-extremes/", views.MeetingExtremesView.as_view(), name="meeting-extremes"),
    path("weekly-extremes/", views.WeeklyExtremesView.as_view(), name="weekly-extremes"),
    path("weekly-averages/", views.WeeklyAveragesView.as_view(), name="weekly-averages"),
    path("top-contacts/", views.TopContactsView.as_view(), name="top-contacts"),
    path("interview-time/", views.InterviewTimeView.as_view(), name="interview-time"),
]
