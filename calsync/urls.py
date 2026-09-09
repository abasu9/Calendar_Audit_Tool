"""Map ``/api/`` sync URLs to manual and webhook actions."""

from django.urls import path

from . import views

urlpatterns = [
    # Let a dashboard user request a backup sync.
    path("sync/", views.manual_sync, name="manual-sync"),

    # Receive change notifications sent by Google Calendar.
    path("webhook/", views.webhook, name="webhook"),
]
