"""Combine health, synchronization, and audit routes under ``/api/``."""

from django.urls import include, path

from .views import health

urlpatterns = [
    # Expose a small application and database readiness check.
    path("health/", health, name="health"),

    # Include manual sync and Google webhook routes.
    path("", include("calsync.urls")),

    # Include the audit dashboard and metric routes.
    path("audit/", include("calaudit.urls")),
]
