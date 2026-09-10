"""Wipe and recreate all calsync tables with per-user scoping.

The old schema used ``google_event_id`` and ``calendar_id`` as primary keys,
making it impossible to store the same event for two different users. The new
schema uses a surrogate ``id`` primary key with ``unique_together`` constraints
and foreign keys to the Django user model.

All existing rows are dropped; users must re-authenticate to re-populate the
tables for their account.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("calsync", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Drop the old tables entirely ─────────────────────────────────────
        migrations.DeleteModel(name="CalendarEvent"),
        migrations.DeleteModel(name="SyncState"),
        migrations.DeleteModel(name="WatchChannel"),

        # ── Recreate CalendarEvent with user FK ──────────────────────────────
        migrations.CreateModel(
            name="CalendarEvent",
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
                    "user",
                    models.ForeignKey(
                        help_text="User who owns this event",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="calendar_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "google_event_id",
                    models.CharField(
                        help_text="Google's unique event identifier",
                        max_length=1024,
                    ),
                ),
                (
                    "calendar_id",
                    models.CharField(
                        db_index=True,
                        help_text="Calendar ID (usually 'primary')",
                        max_length=255,
                    ),
                ),
                (
                    "summary",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Event title/summary",
                        max_length=1024,
                    ),
                ),
                (
                    "start_time",
                    models.DateTimeField(
                        db_index=True,
                        help_text="Event start time (UTC)",
                    ),
                ),
                (
                    "end_time",
                    models.DateTimeField(help_text="Event end time (UTC)"),
                ),
                (
                    "all_day",
                    models.BooleanField(
                        default=False,
                        help_text="True if this is an all-day event",
                    ),
                ),
                (
                    "duration_minutes",
                    models.IntegerField(
                        default=0,
                        help_text="Duration in minutes (computed from start/end)",
                    ),
                ),
                (
                    "attendee_count",
                    models.IntegerField(
                        default=0,
                        help_text="Number of attendees",
                    ),
                ),
                (
                    "organizer_email",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Organizer's email address",
                        max_length=255,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        db_index=True,
                        default="confirmed",
                        help_text="Event status (confirmed/tentative/cancelled)",
                        max_length=50,
                    ),
                ),
                (
                    "raw_json",
                    models.JSONField(
                        default=dict,
                        help_text="Full event data from Google API",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When we first synced this event",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="When we last updated this event",
                    ),
                ),
            ],
            options={
                "ordering": ["-start_time"],
            },
        ),
        migrations.AddConstraint(
            model_name="calendarevent",
            constraint=models.UniqueConstraint(
                fields=("user", "google_event_id"),
                name="calsync_calendarevent_user_event_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="calendarevent",
            index=models.Index(
                fields=["user", "calendar_id", "start_time"],
                name="calsync_calendarevent_user_cal_start_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="calendarevent",
            index=models.Index(
                fields=["user", "calendar_id", "status"],
                name="calsync_calendarevent_user_cal_status_idx",
            ),
        ),

        # ── Recreate SyncState with user FK ──────────────────────────────────
        migrations.CreateModel(
            name="SyncState",
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
                    "user",
                    models.ForeignKey(
                        help_text="User whose calendar is being tracked",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sync_states",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "calendar_id",
                    models.CharField(
                        help_text="Calendar ID (usually 'primary')",
                        max_length=255,
                    ),
                ),
                (
                    "sync_token",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Google's syncToken for incremental sync",
                        max_length=1024,
                    ),
                ),
                (
                    "last_full_sync",
                    models.DateTimeField(
                        blank=True,
                        help_text="When we last did a complete sync",
                        null=True,
                    ),
                ),
                (
                    "last_sync",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="When we last synced (any type)",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="syncstate",
            constraint=models.UniqueConstraint(
                fields=("user", "calendar_id"),
                name="calsync_syncstate_user_cal_uniq",
            ),
        ),

        # ── Recreate WatchChannel with user FK ───────────────────────────────
        migrations.CreateModel(
            name="WatchChannel",
            fields=[
                (
                    "channel_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        help_text="Our UUID for this watch channel",
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="User whose calendar is being watched",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="watch_channels",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resource_id",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Google's resource ID for this channel",
                        max_length=255,
                    ),
                ),
                (
                    "calendar_id",
                    models.CharField(
                        db_index=True,
                        help_text="Calendar ID being watched",
                        max_length=255,
                    ),
                ),
                (
                    "webhook_url",
                    models.URLField(help_text="Webhook URL for notifications"),
                ),
                (
                    "token",
                    models.CharField(
                        help_text="Secret token to verify notifications",
                        max_length=256,
                    ),
                ),
                (
                    "expiration",
                    models.DateTimeField(help_text="When this channel expires"),
                ),
                (
                    "active",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        help_text="Whether this channel is active",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When we created this channel",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
