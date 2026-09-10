"""Store per-user Google OAuth credentials.

Tokens are written here after each successful authorization and updated on every
refresh. The ``client_id`` and ``client_secret`` come from ``credentials.json``
at runtime so they are never duplicated across rows.
"""

from django.conf import settings
from django.db import models


class GoogleCredential(models.Model):
    """Hold the Google OAuth tokens for one Django user.

    The ``google_sub`` field is Google's stable user identifier (the ``sub``
    claim from the ID token). It is used to look up an existing account when the
    same Google user signs in again. ``email`` is stored for display only; the
    ``user`` foreign key is the authoritative link.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_credential",
        help_text="Django user that owns these credentials",
    )
    google_sub = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Google account subject identifier (stable, from ID token)",
    )
    email = models.EmailField(
        blank=True,
        default="",
        help_text="Google account email (display only)",
    )
    token = models.TextField(
        help_text="Current OAuth access token",
    )
    refresh_token = models.TextField(
        blank=True,
        default="",
        help_text="Long-lived refresh token (empty after refresh responses)",
    )
    token_uri = models.CharField(
        max_length=255,
        default="https://oauth2.googleapis.com/token",
        help_text="Token endpoint URL",
    )
    scopes = models.JSONField(
        default=list,
        help_text="Scopes that were granted",
    )
    expiry = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the access token expires (UTC)",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this row was last written",
    )

    class Meta:
        """Show the most recently updated credentials first."""

        ordering = ["-updated_at"]

    def __str__(self):
        """Return the Google email associated with these credentials."""

        return f"GoogleCredential({self.email or self.user})"
