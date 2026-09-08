"""
Google Calendar URL Configuration

PURPOSE:
URL routing for Google OAuth flow and calendar dashboard.
These URLs are mounted at the root (/) in config/urls.py.

ENDPOINTS:
- GET /                  -> Dashboard (auth status + calendar preview)
- GET /oauth2/start/     -> Redirects to Google consent screen
- GET /oauth2/callback/  -> Handles Google's redirect after consent

OAUTH FLOW:
1. User visits / and sees "Connect Google Calendar" button
2. User clicks button -> redirected to /oauth2/start/
3. /oauth2/start/ redirects to Google (accounts.google.com/...)
4. User approves on Google
5. Google redirects to /oauth2/callback/?code=XXX&state=YYY
6. /oauth2/callback/ exchanges code for tokens, saves them
7. /oauth2/callback/ redirects back to /
8. User now sees their calendar events
"""

from django.urls import path

from . import views

urlpatterns = [
    # Main dashboard - shows auth status and calendar preview
    # If not authorized: shows "Connect" button
    # If authorized: shows upcoming events
    path("", views.dashboard, name="dashboard"),
    
    # Start OAuth flow - redirects to Google's consent screen
    # Saves state and PKCE verifier in session before redirecting
    path("oauth2/start/", views.oauth_start, name="oauth_start"),
    
    # OAuth callback - Google redirects here after user consents
    # Exchanges authorization code for access/refresh tokens
    # Saves tokens and redirects to dashboard
    path("oauth2/callback/", views.oauth_callback, name="oauth_callback"),
]
