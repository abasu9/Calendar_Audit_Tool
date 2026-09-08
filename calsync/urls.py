"""
Calendar Sync URL Configuration

PURPOSE:
URL routing for the calendar sync system.
These URLs are mounted under /api/ in config/api_urls.py.

ENDPOINTS:
- POST /api/webhook/ -> Receive Google push notifications
"""

from django.urls import path

from . import views

urlpatterns = [
    # Google push notification webhook
    # Google POSTs here when calendar events change
    # Full URL: /api/webhook/
    path("webhook/", views.webhook, name="webhook"),
]
