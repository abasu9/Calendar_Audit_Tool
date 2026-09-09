"""Provide project-wide endpoints that do not belong to one app."""

from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Report whether the web application can reach its database.

    A small ``SELECT 1`` query verifies the active connection. The public endpoint
    returns HTTP 200 when it succeeds and HTTP 503 with the error when it fails.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover - surfaced via the endpoint
        return Response({"status": "error", "database": str(exc)}, status=503)

    return Response({"status": "ok", "database": "ok"})
