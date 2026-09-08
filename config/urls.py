"""
Root URL Configuration

PURPOSE:
This is the main URL routing file for the entire Django project.
It maps URL patterns to views (or includes other URL files).

HOW DJANGO URL ROUTING WORKS:
1. User requests a URL, e.g., /api/health/
2. Django starts at ROOT_URLCONF (this file)
3. Checks each pattern in urlpatterns[] in order
4. First match wins - calls that view
5. If no match, returns 404

URL PATTERNS DEFINED HERE:
- /admin/              -> Django admin interface
- /api/*               -> API endpoints (from config.api_urls)
- /*                   -> Google Calendar views (from googlecal.urls)

INCLUDE() VS DIRECT PATH:
- path("admin/", admin.site.urls) -> Direct reference to Django's admin URLs
- path("api/", include("config.api_urls")) -> Delegates to another URL file
  All URLs in config.api_urls are prefixed with "api/"
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django admin interface (user management, database browser, etc.)
    # Access at: /admin/
    path("admin/", admin.site.urls),
    
    # API endpoints (health check, and later the audit report API)
    # Delegates to config/api_urls.py
    # All URLs there become /api/...
    path("api/", include("config.api_urls")),
    
    # Google Calendar OAuth and dashboard
    # Delegates to googlecal/urls.py
    # Empty prefix means these are at the root: /, /oauth2/start/, /oauth2/callback/
    path("", include("googlecal.urls")),
]
