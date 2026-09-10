"""Create the GoogleCredential table for per-user OAuth token storage."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GoogleCredential",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "google_sub",
                    models.CharField(
                        db_index=True,
                        help_text="Google account subject identifier (stable, from ID token)",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "email",
                    models.EmailField(
                        blank=True,
                        default="",
                        help_text="Google account email (display only)",
                        max_length=254,
                    ),
                ),
                (
                    "token",
                    models.TextField(help_text="Current OAuth access token"),
                ),
                (
                    "refresh_token",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Long-lived refresh token (empty after refresh responses)",
                    ),
                ),
                (
                    "token_uri",
                    models.CharField(
                        default="https://oauth2.googleapis.com/token",
                        help_text="Token endpoint URL",
                        max_length=255,
                    ),
                ),
                (
                    "scopes",
                    models.JSONField(
                        default=list,
                        help_text="Scopes that were granted",
                    ),
                ),
                (
                    "expiry",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the access token expires (UTC)",
                        null=True,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="When this row was last written",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        help_text="Django user that owns these credentials",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="google_credential",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
    ]
