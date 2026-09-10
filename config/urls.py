"""Define the top-level routes for the Django project.

Django checks these entries in order and delegates each URL group to the app
that owns it.
"""

from django.urls import include, path

urlpatterns = [
    # JSON APIs, webhook handling, and the audit dashboard.
    path("api/", include("config.api_urls")),

    # The main dashboard and Google authorization pages.
    path("", include("googlecal.urls")),
]
