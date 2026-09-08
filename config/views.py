"""
Project-Level Views (Health Check Endpoint)

PURPOSE:
This module contains views that aren't tied to any specific app.
Currently just the health check endpoint used for monitoring.

USAGE:
    curl http://localhost:8000/api/health/
    # Returns: {"status": "ok", "database": "ok"}
"""

from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """
    Health check endpoint for monitoring and load balancers.
    
    WHAT THIS DOES:
    1. Execute a simple query against the database
    2. If successful: return 200 OK with status info
    3. If database fails: return 503 Service Unavailable
    
    WHY THIS EXISTS:
    - Load balancers (nginx, AWS ALB, etc.) ping this to check if the app is alive
    - Monitoring systems (Datadog, etc.) use it for uptime tracking
    - Developers can quickly verify the app + database are working
    
    DECORATORS:
    - @api_view(["GET"]): Only accept GET requests, use DRF's request/response
    - @permission_classes([AllowAny]): No authentication required (public endpoint)
    
    RETURNS:
    - HTTP 200 with {"status": "ok", "database": "ok"} if healthy
    - HTTP 503 with {"status": "error", "database": "<error message>"} if unhealthy
    """
    try:
        # Try a simple database query
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover - surfaced via the endpoint
        # Database connection failed
        return Response({"status": "error", "database": str(exc)}, status=503)

    # Everything is healthy
    return Response({"status": "ok", "database": "ok"})
