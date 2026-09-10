"""Map root URLs to the dashboard and Google OAuth flow."""

from django.urls import path

from . import views

urlpatterns = [
    # Show either the connect action or the user's calendar preview.
    path("", views.dashboard, name="dashboard"),

    # Start authorization, then receive Google's result.
    path("oauth2/start/", views.oauth_start, name="oauth_start"),
    path("oauth2/callback/", views.oauth_callback, name="oauth_callback"),

    # Sign out and return to the dashboard.
    path("logout/", views.logout_view, name="logout"),
]
