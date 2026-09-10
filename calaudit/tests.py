"""Verify audit calculations and their REST endpoints.

Each group creates small per-user calendar datasets, calls a query or view, and
checks the returned totals, filtering rules, parameter limits, empty-data
behaviour, cross-user isolation, and authentication requirements.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from calsync.models import CalendarEvent, EventAttendee
from .queries import (
    BUSY_THRESHOLD_MINUTES,
    INTERVIEW_KEYWORDS,
    RELAXED_THRESHOLD_MINUTES,
    classify_week,
    get_interview_time,
    get_meeting_extremes,
    get_monthly_meeting_time,
    get_top_contacts,
    get_weekly_averages,
    get_weekly_extremes,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username="testuser", email="test@example.com"):
    return User.objects.create_user(username=username, email=email)


def _attendee(event, user, email, *, display_name="", is_self=False):
    """Create an EventAttendee row for the given event."""
    return EventAttendee.objects.create(
        event=event,
        user=user,
        email=email,
        display_name=display_name,
        is_self=is_self,
    )


def _event(user, event_id, **kwargs):
    """Create a confirmed timed CalendarEvent with sensible defaults."""
    now = timezone.now()
    defaults = dict(
        user=user,
        google_event_id=event_id,
        calendar_id="primary",
        summary="Meeting",
        start_time=now - timedelta(days=15),
        end_time=now - timedelta(days=15) + timedelta(hours=1),
        duration_minutes=60,
        all_day=False,
        status="confirmed",
    )
    defaults.update(kwargs)
    return CalendarEvent.objects.create(**defaults)


# ---------------------------------------------------------------------------
# get_monthly_meeting_time
# ---------------------------------------------------------------------------

class GetMonthlyMeetingTimeTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.now = timezone.now()

        one_month_ago = self.now - timedelta(days=30)
        _event(self.user, "e1", start_time=one_month_ago,
               end_time=one_month_ago + timedelta(minutes=30), duration_minutes=30)
        _event(self.user, "e2", start_time=one_month_ago + timedelta(hours=2),
               end_time=one_month_ago + timedelta(hours=3), duration_minutes=60)

        two_months_ago = self.now - timedelta(days=60)
        _event(self.user, "e3", start_time=two_months_ago,
               end_time=two_months_ago + timedelta(minutes=45), duration_minutes=45)

    def test_returns_list(self):
        self.assertIsInstance(get_monthly_meeting_time(self.user), list)

    def test_returns_correct_structure(self):
        for item in get_monthly_meeting_time(self.user):
            for key in ("month", "label", "total_minutes", "total_hours"):
                self.assertIn(key, item)

    def test_sums_minutes_per_month(self):
        result = get_monthly_meeting_time(self.user)
        expected_month = (self.now - timedelta(days=30)).strftime("%Y-%m")
        month_data = next((i for i in result if i["month"] == expected_month), None)
        if month_data:
            self.assertEqual(month_data["total_minutes"], 90)

    def test_excludes_all_day_events(self):
        _event(self.user, "all-day", all_day=True, duration_minutes=0)
        total = sum(i["total_minutes"] for i in get_monthly_meeting_time(self.user))
        self.assertEqual(total, 135)

    def test_excludes_cancelled(self):
        _event(self.user, "cancelled", status="cancelled", duration_minutes=60)
        total = sum(i["total_minutes"] for i in get_monthly_meeting_time(self.user))
        self.assertEqual(total, 135)

    def test_months_parameter_limits_window(self):
        four_months_ago = self.now - timedelta(days=120)
        _event(self.user, "old", start_time=four_months_ago,
               end_time=four_months_ago + timedelta(hours=2), duration_minutes=120)
        total_3 = sum(i["total_minutes"] for i in get_monthly_meeting_time(self.user, months=3))
        total_6 = sum(i["total_minutes"] for i in get_monthly_meeting_time(self.user, months=6))
        self.assertEqual(total_6 - total_3, 120)

    def test_empty_results(self):
        CalendarEvent.objects.all().delete()
        self.assertEqual(get_monthly_meeting_time(self.user), [])

    def test_month_format(self):
        for item in get_monthly_meeting_time(self.user):
            self.assertRegex(item["month"], r"^\d{4}-\d{2}$")

    def test_label_format(self):
        for item in get_monthly_meeting_time(self.user):
            self.assertRegex(item["label"], r"^[A-Z][a-z]+ \d{4}$")

    def test_does_not_include_other_users_events(self):
        other = make_user("other", "other@example.com")
        _event(other, "other-e1", duration_minutes=999)
        total = sum(i["total_minutes"] for i in get_monthly_meeting_time(self.user))
        self.assertEqual(total, 135)


# ---------------------------------------------------------------------------
# get_meeting_extremes
# ---------------------------------------------------------------------------

class GetMeetingExtremesTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.now = timezone.now()

        one_month_ago = self.now - timedelta(days=30)
        two_months_ago = self.now - timedelta(days=60)

        for i in range(3):
            _event(self.user, f"m1-{i}", start_time=one_month_ago + timedelta(hours=i))
        for i in range(5):
            _event(self.user, f"m2-{i}", start_time=two_months_ago + timedelta(hours=i))

    def test_returns_dict(self):
        self.assertIsInstance(get_meeting_extremes(self.user), dict)

    def test_returns_correct_structure(self):
        result = get_meeting_extremes(self.user)
        for key in ("highest", "lowest", "all_months"):
            self.assertIn(key, result)

    def test_finds_correct_highest(self):
        result = get_meeting_extremes(self.user)
        if result["highest"]:
            self.assertGreaterEqual(result["highest"]["meeting_count"], 4)

    def test_empty_results(self):
        CalendarEvent.objects.all().delete()
        result = get_meeting_extremes(self.user)
        self.assertIsNone(result["highest"])
        self.assertIsNone(result["lowest"])

    def test_isolates_from_other_users(self):
        other = make_user("other", "other@example.com")
        for i in range(10):
            _event(other, f"other-{i}", start_time=self.now - timedelta(days=30))
        result = get_meeting_extremes(self.user)
        total = sum(m["meeting_count"] for m in result["all_months"])
        self.assertEqual(total, 8)  # 3 + 5, not the other user's 10


# ---------------------------------------------------------------------------
# classify_week
# ---------------------------------------------------------------------------

class ClassifyWeekTests(TestCase):
    def test_busy(self):
        self.assertEqual(classify_week(301), "busy")

    def test_relaxed(self):
        self.assertEqual(classify_week(119), "relaxed")

    def test_normal(self):
        self.assertEqual(classify_week(200), "normal")


# ---------------------------------------------------------------------------
# get_weekly_extremes
# ---------------------------------------------------------------------------

class GetWeeklyExtremesTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.now = timezone.now()

        one_week_ago = self.now - timedelta(days=7)
        for i in range(6):
            _event(self.user, f"w1-{i}", duration_minutes=60,
                   start_time=one_week_ago + timedelta(hours=i),
                   end_time=one_week_ago + timedelta(hours=i+1))

        two_weeks_ago = self.now - timedelta(days=14)
        _event(self.user, "w2-0", duration_minutes=60,
               start_time=two_weeks_ago, end_time=two_weeks_ago + timedelta(hours=1))

    def test_returns_dict(self):
        self.assertIsInstance(get_weekly_extremes(self.user), dict)

    def test_finds_busiest_week(self):
        result = get_weekly_extremes(self.user)
        if result["busiest"]:
            self.assertEqual(result["busiest"]["total_minutes"], 360)

    def test_empty_results(self):
        CalendarEvent.objects.all().delete()
        result = get_weekly_extremes(self.user)
        self.assertIsNone(result["busiest"])
        self.assertIsNone(result["most_relaxed"])

    def test_isolates_from_other_users(self):
        other = make_user("other", "other@example.com")
        for i in range(10):
            _event(other, f"other-{i}", duration_minutes=999)
        result = get_weekly_extremes(self.user)
        if result["busiest"]:
            self.assertEqual(result["busiest"]["total_minutes"], 360)


# ---------------------------------------------------------------------------
# get_weekly_averages
# ---------------------------------------------------------------------------

class GetWeeklyAveragesTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.now = timezone.now()

        w1 = self.now - timedelta(days=7)
        for i in range(4):
            _event(self.user, f"a1-{i}", duration_minutes=60,
                   start_time=w1 + timedelta(hours=i), end_time=w1 + timedelta(hours=i+1))

        w2 = self.now - timedelta(days=14)
        for i in range(2):
            _event(self.user, f"a2-{i}", duration_minutes=60,
                   start_time=w2 + timedelta(hours=i), end_time=w2 + timedelta(hours=i+1))

    def test_calculates_averages(self):
        result = get_weekly_averages(self.user)
        self.assertEqual(result["weeks_analyzed"], 2)
        self.assertEqual(result["average_meetings_per_week"], 3.0)
        self.assertEqual(result["average_minutes_per_week"], 180.0)

    def test_empty_results(self):
        CalendarEvent.objects.all().delete()
        result = get_weekly_averages(self.user)
        self.assertEqual(result["weeks_analyzed"], 0)
        self.assertEqual(result["average_meetings_per_week"], 0)


# ---------------------------------------------------------------------------
# get_top_contacts
# ---------------------------------------------------------------------------

class GetTopContactsTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.now = timezone.now()
        w = self.now - timedelta(days=7)

        ev1 = CalendarEvent.objects.create(
            user=self.user, google_event_id="c1", calendar_id="primary",
            summary="Sync", start_time=w, end_time=w + timedelta(hours=1),
            duration_minutes=60, all_day=False, status="confirmed",
            raw_json={"id": "c1", "attendees": [
                {"email": "alice@example.com"},
                {"email": "me@example.com", "self": True},
            ]},
        )
        _attendee(ev1, self.user, "alice@example.com", display_name="Alice")
        _attendee(ev1, self.user, "me@example.com", is_self=True)

        ev2 = CalendarEvent.objects.create(
            user=self.user, google_event_id="c2", calendar_id="primary",
            summary="1:1", start_time=w + timedelta(hours=2), end_time=w + timedelta(hours=3),
            duration_minutes=60, all_day=False, status="confirmed",
            raw_json={"id": "c2", "attendees": [
                {"email": "alice@example.com"},
                {"email": "me@example.com", "self": True},
            ]},
        )
        _attendee(ev2, self.user, "alice@example.com", display_name="Alice")
        _attendee(ev2, self.user, "me@example.com", is_self=True)

    def test_alice_is_top_contact(self):
        result = get_top_contacts(self.user)
        self.assertGreater(len(result["top_contacts"]), 0)
        self.assertEqual(result["top_contacts"][0]["email"], "alice@example.com")
        self.assertEqual(result["top_contacts"][0]["meeting_count"], 2)

    def test_excludes_self(self):
        emails = [c["email"] for c in get_top_contacts(self.user)["all_contacts"]]
        self.assertNotIn("me@example.com", emails)

    def test_isolates_from_other_users(self):
        other = make_user("other", "other@example.com")
        other_ev = CalendarEvent.objects.create(
            user=other, google_event_id="o1", calendar_id="primary",
            summary="Other", start_time=timezone.now() - timedelta(days=1),
            end_time=timezone.now(), duration_minutes=60, all_day=False, status="confirmed",
            raw_json={"id": "o1", "attendees": [{"email": "xray@example.com"}]},
        )
        _attendee(other_ev, other, "xray@example.com")
        emails = [c["email"] for c in get_top_contacts(self.user)["all_contacts"]]
        self.assertNotIn("xray@example.com", emails)

    def test_empty_results(self):
        CalendarEvent.objects.all().delete()
        result = get_top_contacts(self.user)
        self.assertEqual(result["top_contacts"], [])

    def test_backfill_from_raw_json(self):
        """Backfill migration logic correctly creates EventAttendee from raw_json."""
        from django.test.utils import isolate_apps

        user = make_user("backfill_user", "backfill@example.com")
        w = timezone.now() - timedelta(days=5)
        event = CalendarEvent.objects.create(
            user=user, google_event_id="bf1", calendar_id="primary",
            summary="Backfill Meeting", start_time=w, end_time=w + timedelta(hours=1),
            duration_minutes=60, all_day=False, status="confirmed",
            raw_json={"id": "bf1", "attendees": [
                {"email": "backfill_contact@example.com", "displayName": "B Contact"},
                {"email": "backfill@example.com", "self": True},
            ]},
        )

        # Simulate backfill logic directly (mirrors what the migration does).
        for attendee in (event.raw_json.get("attendees") or []):
            email = attendee.get("email", "")
            if not email:
                continue
            EventAttendee.objects.get_or_create(
                event=event,
                email=email,
                defaults=dict(
                    user=user,
                    display_name=attendee.get("displayName", ""),
                    response_status=attendee.get("responseStatus", ""),
                    is_self=bool(attendee.get("self", False)),
                ),
            )

        self.assertEqual(EventAttendee.objects.filter(event=event).count(), 2)
        result = get_top_contacts(user)
        emails = [c["email"] for c in result["all_contacts"]]
        self.assertIn("backfill_contact@example.com", emails)
        self.assertNotIn("backfill@example.com", emails)


# ---------------------------------------------------------------------------
# get_interview_time
# ---------------------------------------------------------------------------

class GetInterviewTimeTests(TestCase):
    def setUp(self):
        self.user = make_user()
        w = timezone.now() - timedelta(days=7)

        _event(self.user, "i1", summary="Interview - John", duration_minutes=60,
               start_time=w, end_time=w + timedelta(hours=1))
        _event(self.user, "i2", summary="Phone Screen", duration_minutes=30,
               start_time=w + timedelta(hours=2), end_time=w + timedelta(hours=2, minutes=30))
        _event(self.user, "r1", summary="Team Standup", duration_minutes=15,
               start_time=w + timedelta(hours=3), end_time=w + timedelta(hours=3, minutes=15))

    def test_matches_interview_keywords(self):
        result = get_interview_time(self.user)
        summaries = [e["summary"] for e in result["matching_events"]]
        self.assertTrue(any("Interview" in s for s in summaries))
        self.assertTrue(any("Phone Screen" in s for s in summaries))

    def test_excludes_non_interview(self):
        summaries = [e["summary"] for e in get_interview_time(self.user)["matching_events"]]
        self.assertNotIn("Team Standup", summaries)

    def test_calculates_correct_total(self):
        result = get_interview_time(self.user)
        self.assertEqual(result["total_meetings"], 2)
        self.assertEqual(result["total_minutes"], 90)

    def test_empty_results(self):
        CalendarEvent.objects.all().delete()
        result = get_interview_time(self.user)
        self.assertEqual(result["total_meetings"], 0)
        self.assertEqual(result["matching_events"], [])

    def test_isolates_from_other_users(self):
        other = make_user("other", "other@example.com")
        w = timezone.now() - timedelta(days=3)
        _event(other, "oi1", summary="Interview at Other Corp",
               duration_minutes=120, start_time=w, end_time=w + timedelta(hours=2))
        result = get_interview_time(self.user)
        self.assertEqual(result["total_meetings"], 2)


# ---------------------------------------------------------------------------
# REST API views — authentication required
# ---------------------------------------------------------------------------

class AuditDashboardViewTests(TestCase):
    """The audit dashboard requires authentication."""

    def setUp(self):
        self.user = make_user()
        self.url = reverse("calaudit:dashboard")

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, [302, 403])

    def test_authenticated_user_gets_200(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class MonthlyMeetingTimeViewTests(APITestCase):
    """Test MonthlyMeetingTimeView — requires login."""

    def setUp(self):
        self.user = make_user()
        self.url = reverse("calaudit:monthly-time")
        _event(self.user, "api-e1")

    def test_anonymous_returns_403(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_response_structure(self):
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        self.assertIn("metric", data)
        self.assertIn("data", data)
        self.assertEqual(data["metric"], "monthly_meeting_time")

    def test_default_period(self):
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        self.assertEqual(data["period"], "last_3_months")

    def test_months_clamped_maximum(self):
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url, {"months": 24}).json()
        self.assertEqual(data["period"], "last_12_months")

    def test_other_user_data_not_returned(self):
        other = make_user("other", "other@example.com")
        _event(other, "other-e1", duration_minutes=9999)
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        total = sum(d["total_minutes"] for d in data["data"])
        self.assertEqual(total, 60)  # only self.user's 60-min event

    def test_empty_database(self):
        CalendarEvent.objects.all().delete()
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        self.assertEqual(data["data"], [])


class MeetingExtremesViewTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.url = reverse("calaudit:meeting-extremes")
        one_month_ago = timezone.now() - timedelta(days=30)
        for i in range(3):
            _event(self.user, f"me-{i}", start_time=one_month_ago + timedelta(hours=i),
                   end_time=one_month_ago + timedelta(hours=i+1))

    def test_anonymous_returns_403(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_response_structure(self):
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        for key in ("metric", "period", "highest", "lowest", "all_months"):
            self.assertIn(key, data)

    def test_empty_database(self):
        CalendarEvent.objects.all().delete()
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        self.assertIsNone(data["highest"])
        self.assertIsNone(data["lowest"])


class WeeklyExtremesViewTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.url = reverse("calaudit:weekly-extremes")
        w = timezone.now() - timedelta(days=7)
        for i in range(4):
            _event(self.user, f"we-{i}", start_time=w + timedelta(hours=i),
                   end_time=w + timedelta(hours=i+1))

    def test_anonymous_returns_403(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)


class WeeklyAveragesViewTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.url = reverse("calaudit:weekly-averages")
        w = timezone.now() - timedelta(days=7)
        for i in range(3):
            _event(self.user, f"wa-{i}", start_time=w + timedelta(hours=i),
                   end_time=w + timedelta(hours=i+1))

    def test_anonymous_returns_403(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_response_structure(self):
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        for key in ("weeks_analyzed", "average_meetings_per_week", "weekly_data"):
            self.assertIn(key, data)


class TopContactsViewTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.url = reverse("calaudit:top-contacts")
        w = timezone.now() - timedelta(days=7)
        ev = CalendarEvent.objects.create(
            user=self.user, google_event_id="tc-1", calendar_id="primary",
            summary="Sync", start_time=w, end_time=w + timedelta(hours=1),
            duration_minutes=60, all_day=False, status="confirmed",
            raw_json={"id": "tc-1", "attendees": [
                {"email": "alice@example.com"},
                {"email": "me@example.com", "self": True},
            ]},
        )
        _attendee(ev, self.user, "alice@example.com", display_name="Alice")
        _attendee(ev, self.user, "me@example.com", is_self=True)

    def test_anonymous_returns_403(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_response_contains_contact(self):
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        emails = [c["email"] for c in data["all_contacts"]]
        self.assertIn("alice@example.com", emails)

    def test_empty_database(self):
        CalendarEvent.objects.all().delete()
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        self.assertEqual(data["top_contacts"], [])


class InterviewTimeViewTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.url = reverse("calaudit:interview-time")
        w = timezone.now() - timedelta(days=7)
        _event(self.user, "iv-1", summary="Technical Interview",
               start_time=w, end_time=w + timedelta(hours=1), duration_minutes=60)

    def test_anonymous_returns_403(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_finds_interview_event(self):
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        self.assertGreaterEqual(data["total_meetings"], 1)
        summaries = [e["summary"] for e in data["matching_events"]]
        self.assertIn("Technical Interview", summaries)

    def test_empty_database(self):
        CalendarEvent.objects.all().delete()
        self.client.force_authenticate(user=self.user)
        data = self.client.get(self.url).json()
        self.assertEqual(data["total_meetings"], 0)
