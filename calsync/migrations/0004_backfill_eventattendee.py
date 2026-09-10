"""Backfill EventAttendee rows from existing CalendarEvent.raw_json.

This migration reads attendee data that was already stored in the raw_json
column and creates the corresponding EventAttendee rows. No Google API calls
are made. The operation is idempotent: because EventAttendee has a
unique_together on (event, email), duplicate rows raised by a partial previous
run are silently ignored via update_conflicts / ignore_conflicts.

The reverse migration is a no-op because the canonical source (raw_json) is
unchanged and the schema migration (0003) handles the table drop if rolled back.
"""

from django.db import migrations


def backfill_attendees(apps, schema_editor):
    CalendarEvent = apps.get_model("calsync", "CalendarEvent")
    EventAttendee = apps.get_model("calsync", "EventAttendee")

    batch = []
    BATCH_SIZE = 500

    for event in CalendarEvent.objects.iterator(chunk_size=200):
        raw = event.raw_json or {}
        for attendee in raw.get("attendees") or []:
            email = attendee.get("email", "")
            if not email:
                continue
            batch.append(
                EventAttendee(
                    event=event,
                    user_id=event.user_id,
                    email=email,
                    display_name=attendee.get("displayName", ""),
                    response_status=attendee.get("responseStatus", ""),
                    is_self=bool(attendee.get("self", False)),
                )
            )
            if len(batch) >= BATCH_SIZE:
                EventAttendee.objects.bulk_create(
                    batch, ignore_conflicts=True
                )
                batch = []

    if batch:
        EventAttendee.objects.bulk_create(batch, ignore_conflicts=True)


def noop(apps, schema_editor):
    """Reversing drops the table (handled by 0003); nothing to undo here."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("calsync", "0003_eventattendee"),
    ]

    operations = [
        migrations.RunPython(backfill_attendees, noop),
    ]
