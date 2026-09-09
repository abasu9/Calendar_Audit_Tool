"""
API URL Configuration

PURPOSE:
URL routing for REST API endpoints.
All URLs here are prefixed with /api/ (see config/urls.py).

ENDPOINTS:
- GET /api/health/ -> Health check endpoint
- POST /api/sync/ -> User-requested calendar sync
- POST /api/webhook/ -> Google push notification receiver (from calsync app)

FUTURE ENDPOINTS (Phase 3):
- GET /api/report/ -> Audit report data
- GET /api/metrics/ -> Calendar metrics
"""

from django.urls import include, path

from .views import health

urlpatterns = [
    # Health check endpoint
    # Full URL: /api/health/
    # Used by load balancers and monitoring to verify the app is running
    path("health/", health, name="health"),
    
    # Calendar sync endpoints (webhook, etc.)
    # Mounts calsync/urls.py here
    # Full URL: /api/webhook/
    path("", include("calsync.urls")),
    
    # Audit report endpoints (Phase 3)
    # Mounts calaudit/urls.py here
    # Full URL: /api/audit/monthly-time/, etc.
    path("audit/", include("calaudit.urls")),
]
