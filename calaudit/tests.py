"""Verify audit calculations and their REST endpoints.

Each group creates small calendar datasets, calls a query or view, and checks the
returned totals, filtering rules, parameter limits, and empty-data behavior.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from calsync.models import CalendarEvent
from .queries import (
    classify_week,
    get_interview_time,
    get_meeting_extremes,
    get_monthly_meeting_time,
    get_top_contacts,
    get_weekly_averages,
    get_weekly_extremes,
    BUSY_THRESHOLD_MINUTES,
    INTERVIEW_KEYWORDS,
    RELAXED_THRESHOLD_MINUTES,
)


class GetMonthlyMeetingTimeTests(TestCase):
    """
    Test cases for the get_monthly_meeting_time() query function.
    """
    
    def setUp(self):
        """
        Create test events before each test.
        """
        # Current time for reference
        self.now = timezone.now()
        
        # Create events in different months
        # Event 1: 30 minutes, 1 month ago
        one_month_ago = self.now - timedelta(days=30)
        CalendarEvent.objects.create(
            google_event_id="test-event-1",
            calendar_id="primary",
            summary="Meeting 1",
            start_time=one_month_ago,
            end_time=one_month_ago + timedelta(minutes=30),
            duration_minutes=30,
            all_day=False,
            status="confirmed",
        )
        
        # Event 2: 60 minutes, 1 month ago (same month as event 1)
        CalendarEvent.objects.create(
            google_event_id="test-event-2",
            calendar_id="primary",
            summary="Meeting 2",
            start_time=one_month_ago + timedelta(hours=2),
            end_time=one_month_ago + timedelta(hours=3),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
        
        # Event 3: 45 minutes, 2 months ago
        two_months_ago = self.now - timedelta(days=60)
        CalendarEvent.objects.create(
            google_event_id="test-event-3",
            calendar_id="primary",
            summary="Meeting 3",
            start_time=two_months_ago,
            end_time=two_months_ago + timedelta(minutes=45),
            duration_minutes=45,
            all_day=False,
            status="confirmed",
        )
    
    def test_returns_list(self):
        """
        get_monthly_meeting_time() should return a list.
        """
        result = get_monthly_meeting_time()
        self.assertIsInstance(result, list)
    
    def test_returns_correct_structure(self):
        """
        Each item should have month, label, total_minutes, total_hours.
        """
        result = get_monthly_meeting_time()
        
        for item in result:
            self.assertIn("month", item)
            self.assertIn("label", item)
            self.assertIn("total_minutes", item)
            self.assertIn("total_hours", item)
    
    def test_sums_minutes_per_month(self):
        """
        Events in the same month should have their durations summed.
        """
        result = get_monthly_meeting_time()
        
        # Find the month with two events (should have 90 minutes total)
        one_month_ago = self.now - timedelta(days=30)
        expected_month = one_month_ago.strftime("%Y-%m")
        
        month_data = next(
            (item for item in result if item["month"] == expected_month),
            None
        )
        
        if month_data:
            # Events 1 (30 min) + Event 2 (60 min) = 90 minutes
            self.assertEqual(month_data["total_minutes"], 90)
            self.assertEqual(month_data["total_hours"], 1.5)
    
    def test_excludes_all_day_events(self):
        """
        All-day events should not be included in the calculation.
        """
        # Create an all-day event
        CalendarEvent.objects.create(
            google_event_id="test-all-day",
            calendar_id="primary",
            summary="All Day Event",
            start_time=self.now - timedelta(days=15),
            end_time=self.now - timedelta(days=14),
            duration_minutes=0,
            all_day=True,
            status="confirmed",
        )
        
        result = get_monthly_meeting_time()
        
        # All-day events have duration_minutes=0, so they shouldn't affect totals
        # This test verifies the query filters them out
        total_minutes = sum(item["total_minutes"] for item in result)
        
        # Should still be 90 + 45 = 135 (not affected by all-day event)
        self.assertEqual(total_minutes, 135)
    
    def test_excludes_non_confirmed_events(self):
        """
        Only confirmed events should be included.
        """
        # Create a cancelled event
        CalendarEvent.objects.create(
            google_event_id="test-cancelled",
            calendar_id="primary",
            summary="Cancelled Meeting",
            start_time=self.now - timedelta(days=10),
            end_time=self.now - timedelta(days=10) + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="cancelled",
        )
        
        # Create a tentative event
        CalendarEvent.objects.create(
            google_event_id="test-tentative",
            calendar_id="primary",
            summary="Tentative Meeting",
            start_time=self.now - timedelta(days=10),
            end_time=self.now - timedelta(days=10) + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="tentative",
        )
        
        result = get_monthly_meeting_time()
        total_minutes = sum(item["total_minutes"] for item in result)
        
        # Should still be 135 (cancelled and tentative not included)
        self.assertEqual(total_minutes, 135)
    
    def test_months_parameter(self):
        """
        The months parameter should limit how far back we look.
        """
        # Create an event 4 months ago
        four_months_ago = self.now - timedelta(days=120)
        CalendarEvent.objects.create(
            google_event_id="test-old-event",
            calendar_id="primary",
            summary="Old Meeting",
            start_time=four_months_ago,
            end_time=four_months_ago + timedelta(hours=2),
            duration_minutes=120,
            all_day=False,
            status="confirmed",
        )
        
        # With months=3, the old event should not be included
        result_3_months = get_monthly_meeting_time(months=3)
        total_3 = sum(item["total_minutes"] for item in result_3_months)
        
        # With months=6, the old event should be included
        result_6_months = get_monthly_meeting_time(months=6)
        total_6 = sum(item["total_minutes"] for item in result_6_months)
        
        # 6 months should have 120 more minutes than 3 months
        self.assertEqual(total_6 - total_3, 120)
    
    def test_empty_results(self):
        """
        Should return empty list when no events match.
        """
        # Delete all events
        CalendarEvent.objects.all().delete()
        
        result = get_monthly_meeting_time()
        self.assertEqual(result, [])
    
    def test_month_format(self):
        """
        Month should be in YYYY-MM format.
        """
        result = get_monthly_meeting_time()
        
        for item in result:
            # Should match YYYY-MM pattern
            self.assertRegex(item["month"], r"^\d{4}-\d{2}$")
    
    def test_label_format(self):
        """
        Label should be human-readable like "January 2026".
        """
        result = get_monthly_meeting_time()
        
        for item in result:
            # Should contain month name and year
            self.assertRegex(item["label"], r"^[A-Z][a-z]+ \d{4}$")


class MonthlyMeetingTimeViewTests(APITestCase):
    """
    Test cases for the MonthlyMeetingTimeView API endpoint.
    """
    
    def setUp(self):
        """
        Create test events before each test.
        """
        self.now = timezone.now()
        
        # Create a test event
        CalendarEvent.objects.create(
            google_event_id="api-test-event",
            calendar_id="primary",
            summary="API Test Meeting",
            start_time=self.now - timedelta(days=15),
            end_time=self.now - timedelta(days=15) + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
        
        self.url = reverse("calaudit:monthly-time")
    
    def test_get_returns_200(self):
        """
        GET request should return 200 OK.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
    
    def test_response_structure(self):
        """
        Response should have metric, period, and data fields.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIn("metric", data)
        self.assertIn("period", data)
        self.assertIn("data", data)
        
        self.assertEqual(data["metric"], "monthly_meeting_time")
        self.assertIsInstance(data["data"], list)
    
    def test_default_period(self):
        """
        Default period should be last_3_months.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["period"], "last_3_months")
    
    def test_months_parameter(self):
        """
        months query parameter should change the period.
        """
        response = self.client.get(self.url, {"months": 6})
        data = response.json()
        
        self.assertEqual(data["period"], "last_6_months")
    
    def test_invalid_months_defaults_to_3(self):
        """
        Invalid months parameter should default to 3.
        """
        response = self.client.get(self.url, {"months": "invalid"})
        data = response.json()
        
        self.assertEqual(data["period"], "last_3_months")
    
    def test_months_clamped_minimum(self):
        """
        months should be clamped to minimum of 1.
        """
        response = self.client.get(self.url, {"months": 0})
        data = response.json()
        
        self.assertEqual(data["period"], "last_1_months")
    
    def test_months_clamped_maximum(self):
        """
        months should be clamped to maximum of 12.
        """
        response = self.client.get(self.url, {"months": 24})
        data = response.json()
        
        self.assertEqual(data["period"], "last_12_months")
    
    def test_data_contains_events(self):
        """
        Response data should contain the test event's month.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertGreater(len(data["data"]), 0)
        
        # Check first item has correct structure
        first_item = data["data"][0]
        self.assertIn("month", first_item)
        self.assertIn("label", first_item)
        self.assertIn("total_minutes", first_item)
        self.assertIn("total_hours", first_item)
    
    def test_empty_database(self):
        """
        Should return empty data array when no events exist.
        """
        CalendarEvent.objects.all().delete()
        
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["data"], [])


class GetMeetingExtremesTests(TestCase):
    """
    Test cases for the get_meeting_extremes() query function.
    """
    
    def setUp(self):
        """
        Create test events before each test.
        """
        self.now = timezone.now()
        
        # Create 3 events in month 1 (30 days ago)
        one_month_ago = self.now - timedelta(days=30)
        for i in range(3):
            CalendarEvent.objects.create(
                google_event_id=f"month1-event-{i}",
                calendar_id="primary",
                summary=f"Meeting {i}",
                start_time=one_month_ago + timedelta(hours=i),
                end_time=one_month_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
        
        # Create 5 events in month 2 (60 days ago)
        two_months_ago = self.now - timedelta(days=60)
        for i in range(5):
            CalendarEvent.objects.create(
                google_event_id=f"month2-event-{i}",
                calendar_id="primary",
                summary=f"Meeting {i}",
                start_time=two_months_ago + timedelta(hours=i),
                end_time=two_months_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
        
        # Create 1 event in month 3 (20 days ago, same month as month 1 potentially)
        twenty_days_ago = self.now - timedelta(days=20)
        CalendarEvent.objects.create(
            google_event_id="month3-event-0",
            calendar_id="primary",
            summary="Solo Meeting",
            start_time=twenty_days_ago,
            end_time=twenty_days_ago + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
    
    def test_returns_dict(self):
        """
        get_meeting_extremes() should return a dict.
        """
        result = get_meeting_extremes()
        self.assertIsInstance(result, dict)
    
    def test_returns_correct_structure(self):
        """
        Result should have highest, lowest, and all_months keys.
        """
        result = get_meeting_extremes()
        
        self.assertIn("highest", result)
        self.assertIn("lowest", result)
        self.assertIn("all_months", result)
    
    def test_highest_has_correct_structure(self):
        """
        Highest should have month, label, and meeting_count.
        """
        result = get_meeting_extremes()
        
        if result["highest"]:
            self.assertIn("month", result["highest"])
            self.assertIn("label", result["highest"])
            self.assertIn("meeting_count", result["highest"])
    
    def test_finds_correct_highest(self):
        """
        Should find the month with most meetings.
        """
        result = get_meeting_extremes()
        
        # The highest should have at least 4 meetings (we created 5 in one month)
        if result["highest"]:
            self.assertGreaterEqual(result["highest"]["meeting_count"], 4)
    
    def test_finds_correct_lowest(self):
        """
        Should find the month with least meetings.
        """
        result = get_meeting_extremes()
        
        # The lowest should have fewer meetings than highest
        if result["highest"] and result["lowest"]:
            self.assertLessEqual(
                result["lowest"]["meeting_count"],
                result["highest"]["meeting_count"]
            )
    
    def test_excludes_all_day_events(self):
        """
        All-day events should not be counted.
        """
        # Create an all-day event
        CalendarEvent.objects.create(
            google_event_id="all-day-extremes",
            calendar_id="primary",
            summary="All Day Event",
            start_time=self.now - timedelta(days=15),
            end_time=self.now - timedelta(days=14),
            duration_minutes=0,
            all_day=True,
            status="confirmed",
        )
        
        result = get_meeting_extremes()
        total_counted = sum(m["meeting_count"] for m in result["all_months"])
        
        # Should not include the all-day event
        self.assertEqual(total_counted, 9)  # 3 + 5 + 1 = 9
    
    def test_empty_results(self):
        """
        Should return None for highest/lowest when no events.
        """
        CalendarEvent.objects.all().delete()
        
        result = get_meeting_extremes()
        
        self.assertIsNone(result["highest"])
        self.assertIsNone(result["lowest"])
        self.assertEqual(result["all_months"], [])


class MeetingExtremesViewTests(APITestCase):
    """
    Test cases for the MeetingExtremesView API endpoint.
    """
    
    def setUp(self):
        """
        Create test events before each test.
        """
        self.now = timezone.now()
        
        # Create events in different months
        one_month_ago = self.now - timedelta(days=30)
        for i in range(3):
            CalendarEvent.objects.create(
                google_event_id=f"api-extremes-{i}",
                calendar_id="primary",
                summary=f"API Test Meeting {i}",
                start_time=one_month_ago + timedelta(hours=i),
                end_time=one_month_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
        
        self.url = reverse("calaudit:meeting-extremes")
    
    def test_get_returns_200(self):
        """
        GET request should return 200 OK.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
    
    def test_response_structure(self):
        """
        Response should have metric, period, highest, lowest, and all_months.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIn("metric", data)
        self.assertIn("period", data)
        self.assertIn("highest", data)
        self.assertIn("lowest", data)
        self.assertIn("all_months", data)
        
        self.assertEqual(data["metric"], "meeting_extremes")
    
    def test_default_period(self):
        """
        Default period should be last_3_months.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["period"], "last_3_months")
    
    def test_months_parameter(self):
        """
        months query parameter should change the period.
        """
        response = self.client.get(self.url, {"months": 6})
        data = response.json()
        
        self.assertEqual(data["period"], "last_6_months")
    
    def test_highest_contains_data(self):
        """
        Highest should contain meeting count.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIsNotNone(data["highest"])
        self.assertIn("meeting_count", data["highest"])
        self.assertGreater(data["highest"]["meeting_count"], 0)
    
    def test_empty_database(self):
        """
        Should return null for highest/lowest when no events.
        """
        CalendarEvent.objects.all().delete()
        
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIsNone(data["highest"])
        self.assertIsNone(data["lowest"])
        self.assertEqual(data["all_months"], [])


class ClassifyWeekTests(TestCase):
    """
    Test cases for the classify_week() helper function.
    """
    
    def test_busy_week(self):
        """
        More than 300 minutes should be classified as busy.
        """
        self.assertEqual(classify_week(301), "busy")
        self.assertEqual(classify_week(500), "busy")
    
    def test_relaxed_week(self):
        """
        Less than 120 minutes should be classified as relaxed.
        """
        self.assertEqual(classify_week(0), "relaxed")
        self.assertEqual(classify_week(119), "relaxed")
    
    def test_normal_week(self):
        """
        Between 120 and 300 minutes should be classified as normal.
        """
        self.assertEqual(classify_week(120), "normal")
        self.assertEqual(classify_week(200), "normal")
        self.assertEqual(classify_week(300), "normal")


class GetWeeklyExtremesTests(TestCase):
    """
    Test cases for the get_weekly_extremes() query function.
    """
    
    def setUp(self):
        """
        Create test events in different weeks.
        """
        self.now = timezone.now()
        
        # Create 6 hours of meetings in week 1 (7 days ago) - busy
        one_week_ago = self.now - timedelta(days=7)
        for i in range(6):
            CalendarEvent.objects.create(
                google_event_id=f"week1-event-{i}",
                calendar_id="primary",
                summary=f"Busy Meeting {i}",
                start_time=one_week_ago + timedelta(hours=i),
                end_time=one_week_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
        
        # Create 1 hour of meetings in week 2 (14 days ago) - relaxed
        two_weeks_ago = self.now - timedelta(days=14)
        CalendarEvent.objects.create(
            google_event_id="week2-event-0",
            calendar_id="primary",
            summary="Relaxed Meeting",
            start_time=two_weeks_ago,
            end_time=two_weeks_ago + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
        
        # Create 3 hours of meetings in week 3 (21 days ago) - normal
        three_weeks_ago = self.now - timedelta(days=21)
        for i in range(3):
            CalendarEvent.objects.create(
                google_event_id=f"week3-event-{i}",
                calendar_id="primary",
                summary=f"Normal Meeting {i}",
                start_time=three_weeks_ago + timedelta(hours=i),
                end_time=three_weeks_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
    
    def test_returns_dict(self):
        """
        get_weekly_extremes() should return a dict.
        """
        result = get_weekly_extremes()
        self.assertIsInstance(result, dict)
    
    def test_returns_correct_structure(self):
        """
        Result should have threshold, busiest, most_relaxed, and all_weeks.
        """
        result = get_weekly_extremes()
        
        self.assertIn("threshold", result)
        self.assertIn("busiest", result)
        self.assertIn("most_relaxed", result)
        self.assertIn("all_weeks", result)
    
    def test_threshold_values(self):
        """
        Threshold should contain busy_minutes and relaxed_minutes.
        """
        result = get_weekly_extremes()
        
        self.assertEqual(result["threshold"]["busy_minutes"], BUSY_THRESHOLD_MINUTES)
        self.assertEqual(result["threshold"]["relaxed_minutes"], RELAXED_THRESHOLD_MINUTES)
    
    def test_busiest_has_correct_structure(self):
        """
        Busiest should have week, start_date, end_date, meeting_count, total_minutes, classification.
        """
        result = get_weekly_extremes()
        
        if result["busiest"]:
            self.assertIn("week", result["busiest"])
            self.assertIn("start_date", result["busiest"])
            self.assertIn("end_date", result["busiest"])
            self.assertIn("meeting_count", result["busiest"])
            self.assertIn("total_minutes", result["busiest"])
            self.assertIn("classification", result["busiest"])
    
    def test_finds_busiest_week(self):
        """
        Should find the week with most meeting time.
        """
        result = get_weekly_extremes()
        
        if result["busiest"]:
            # The busiest week should have 360 minutes (6 hours)
            self.assertEqual(result["busiest"]["total_minutes"], 360)
            self.assertEqual(result["busiest"]["meeting_count"], 6)
            self.assertEqual(result["busiest"]["classification"], "busy")
    
    def test_finds_most_relaxed_week(self):
        """
        Should find the week with least meeting time.
        """
        result = get_weekly_extremes()
        
        if result["most_relaxed"]:
            # The most relaxed week should have 60 minutes (1 hour)
            self.assertEqual(result["most_relaxed"]["total_minutes"], 60)
            self.assertEqual(result["most_relaxed"]["meeting_count"], 1)
            self.assertEqual(result["most_relaxed"]["classification"], "relaxed")
    
    def test_week_format(self):
        """
        Week should be in ISO format YYYY-Www.
        """
        result = get_weekly_extremes()
        
        for week in result["all_weeks"]:
            # Should match YYYY-Www pattern
            self.assertRegex(week["week"], r"^\d{4}-W\d{2}$")
    
    def test_empty_results(self):
        """
        Should return None for busiest/most_relaxed when no events.
        """
        CalendarEvent.objects.all().delete()
        
        result = get_weekly_extremes()
        
        self.assertIsNone(result["busiest"])
        self.assertIsNone(result["most_relaxed"])
        self.assertEqual(result["all_weeks"], [])


class WeeklyExtremesViewTests(APITestCase):
    """
    Test cases for the WeeklyExtremesView API endpoint.
    """
    
    def setUp(self):
        """
        Create test events before each test.
        """
        self.now = timezone.now()
        
        # Create some meetings in the last week
        one_week_ago = self.now - timedelta(days=7)
        for i in range(4):
            CalendarEvent.objects.create(
                google_event_id=f"api-weekly-{i}",
                calendar_id="primary",
                summary=f"API Weekly Test {i}",
                start_time=one_week_ago + timedelta(hours=i),
                end_time=one_week_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
        
        self.url = reverse("calaudit:weekly-extremes")
    
    def test_get_returns_200(self):
        """
        GET request should return 200 OK.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
    
    def test_response_structure(self):
        """
        Response should have metric, period, threshold, busiest, most_relaxed, and all_weeks.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIn("metric", data)
        self.assertIn("period", data)
        self.assertIn("threshold", data)
        self.assertIn("busiest", data)
        self.assertIn("most_relaxed", data)
        self.assertIn("all_weeks", data)
        
        self.assertEqual(data["metric"], "weekly_extremes")
    
    def test_default_period(self):
        """
        Default period should be last_3_months.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["period"], "last_3_months")
    
    def test_months_parameter(self):
        """
        months query parameter should change the period.
        """
        response = self.client.get(self.url, {"months": 6})
        data = response.json()
        
        self.assertEqual(data["period"], "last_6_months")
    
    def test_threshold_in_response(self):
        """
        Response should include threshold values.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIn("busy_minutes", data["threshold"])
        self.assertIn("relaxed_minutes", data["threshold"])
    
    def test_busiest_contains_data(self):
        """
        Busiest should contain meeting data.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIsNotNone(data["busiest"])
        self.assertIn("total_minutes", data["busiest"])
        self.assertIn("classification", data["busiest"])
    
    def test_empty_database(self):
        """
        Should return null for busiest/most_relaxed when no events.
        """
        CalendarEvent.objects.all().delete()
        
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIsNone(data["busiest"])
        self.assertIsNone(data["most_relaxed"])
        self.assertEqual(data["all_weeks"], [])


class GetWeeklyAveragesTests(TestCase):
    """
    Test cases for the get_weekly_averages() query function.
    """
    
    def setUp(self):
        """
        Create test events in different weeks.
        """
        self.now = timezone.now()
        
        # Week 1: 4 meetings, 4 hours total
        one_week_ago = self.now - timedelta(days=7)
        for i in range(4):
            CalendarEvent.objects.create(
                google_event_id=f"avg-week1-{i}",
                calendar_id="primary",
                summary=f"Meeting Week1 {i}",
                start_time=one_week_ago + timedelta(hours=i),
                end_time=one_week_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
        
        # Week 2: 2 meetings, 2 hours total
        two_weeks_ago = self.now - timedelta(days=14)
        for i in range(2):
            CalendarEvent.objects.create(
                google_event_id=f"avg-week2-{i}",
                calendar_id="primary",
                summary=f"Meeting Week2 {i}",
                start_time=two_weeks_ago + timedelta(hours=i),
                end_time=two_weeks_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
    
    def test_returns_dict(self):
        """
        get_weekly_averages() should return a dict.
        """
        result = get_weekly_averages()
        self.assertIsInstance(result, dict)
    
    def test_returns_correct_structure(self):
        """
        Result should have weeks_analyzed, averages, and weekly_data.
        """
        result = get_weekly_averages()
        
        self.assertIn("weeks_analyzed", result)
        self.assertIn("average_meetings_per_week", result)
        self.assertIn("average_minutes_per_week", result)
        self.assertIn("average_hours_per_week", result)
        self.assertIn("weekly_data", result)
    
    def test_calculates_correct_averages(self):
        """
        Should calculate correct averages across weeks.
        """
        result = get_weekly_averages()
        
        # We have 2 weeks with data
        # Week 1: 4 meetings, 240 minutes
        # Week 2: 2 meetings, 120 minutes
        # Average: 3 meetings/week, 180 minutes/week
        self.assertEqual(result["weeks_analyzed"], 2)
        self.assertEqual(result["average_meetings_per_week"], 3.0)
        self.assertEqual(result["average_minutes_per_week"], 180.0)
        self.assertEqual(result["average_hours_per_week"], 3.0)
    
    def test_weekly_data_structure(self):
        """
        Weekly data should have week, start_date, meeting_count, total_minutes.
        """
        result = get_weekly_averages()
        
        if result["weekly_data"]:
            week = result["weekly_data"][0]
            self.assertIn("week", week)
            self.assertIn("start_date", week)
            self.assertIn("meeting_count", week)
            self.assertIn("total_minutes", week)
    
    def test_empty_results(self):
        """
        Should return 0 averages when no events.
        """
        CalendarEvent.objects.all().delete()
        
        result = get_weekly_averages()
        
        self.assertEqual(result["weeks_analyzed"], 0)
        self.assertEqual(result["average_meetings_per_week"], 0)
        self.assertEqual(result["average_minutes_per_week"], 0)
        self.assertEqual(result["average_hours_per_week"], 0)
        self.assertEqual(result["weekly_data"], [])


class WeeklyAveragesViewTests(APITestCase):
    """
    Test cases for the WeeklyAveragesView API endpoint.
    """
    
    def setUp(self):
        """
        Create test events before each test.
        """
        self.now = timezone.now()
        
        # Create some meetings
        one_week_ago = self.now - timedelta(days=7)
        for i in range(3):
            CalendarEvent.objects.create(
                google_event_id=f"api-avg-{i}",
                calendar_id="primary",
                summary=f"API Avg Test {i}",
                start_time=one_week_ago + timedelta(hours=i),
                end_time=one_week_ago + timedelta(hours=i+1),
                duration_minutes=60,
                all_day=False,
                status="confirmed",
            )
        
        self.url = reverse("calaudit:weekly-averages")
    
    def test_get_returns_200(self):
        """
        GET request should return 200 OK.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
    
    def test_response_structure(self):
        """
        Response should have metric, period, weeks_analyzed, averages, and weekly_data.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIn("metric", data)
        self.assertIn("period", data)
        self.assertIn("weeks_analyzed", data)
        self.assertIn("average_meetings_per_week", data)
        self.assertIn("average_minutes_per_week", data)
        self.assertIn("average_hours_per_week", data)
        self.assertIn("weekly_data", data)
        
        self.assertEqual(data["metric"], "weekly_averages")
    
    def test_default_period(self):
        """
        Default period should be last_3_months.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["period"], "last_3_months")
    
    def test_months_parameter(self):
        """
        months query parameter should change the period.
        """
        response = self.client.get(self.url, {"months": 6})
        data = response.json()
        
        self.assertEqual(data["period"], "last_6_months")
    
    def test_averages_are_numbers(self):
        """
        Averages should be numeric values.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIsInstance(data["average_meetings_per_week"], (int, float))
        self.assertIsInstance(data["average_minutes_per_week"], (int, float))
        self.assertIsInstance(data["average_hours_per_week"], (int, float))
    
    def test_empty_database(self):
        """
        Should return 0 averages when no events.
        """
        CalendarEvent.objects.all().delete()
        
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["weeks_analyzed"], 0)
        self.assertEqual(data["average_meetings_per_week"], 0)
        self.assertEqual(data["weekly_data"], [])


class GetTopContactsTests(TestCase):
    """
    Test cases for the get_top_contacts() query function.
    """
    
    def setUp(self):
        """
        Create test events with attendees.
        """
        self.now = timezone.now()
        one_week_ago = self.now - timedelta(days=7)
        
        # Event 1: Meeting with Alice and Bob
        CalendarEvent.objects.create(
            google_event_id="contacts-event-1",
            calendar_id="primary",
            summary="Team Sync",
            start_time=one_week_ago,
            end_time=one_week_ago + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
            raw_json={
                "id": "contacts-event-1",
                "attendees": [
                    {"email": "alice@example.com", "responseStatus": "accepted"},
                    {"email": "bob@example.com", "responseStatus": "accepted"},
                    {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
                ]
            },
        )
        
        # Event 2: Another meeting with Alice
        CalendarEvent.objects.create(
            google_event_id="contacts-event-2",
            calendar_id="primary",
            summary="1:1 with Alice",
            start_time=one_week_ago + timedelta(hours=2),
            end_time=one_week_ago + timedelta(hours=3),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
            raw_json={
                "id": "contacts-event-2",
                "attendees": [
                    {"email": "alice@example.com", "responseStatus": "accepted"},
                    {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
                ]
            },
        )
        
        # Event 3: Meeting with Charlie (30 min)
        CalendarEvent.objects.create(
            google_event_id="contacts-event-3",
            calendar_id="primary",
            summary="Quick chat with Charlie",
            start_time=one_week_ago + timedelta(hours=4),
            end_time=one_week_ago + timedelta(minutes=30),
            duration_minutes=30,
            all_day=False,
            status="confirmed",
            raw_json={
                "id": "contacts-event-3",
                "attendees": [
                    {"email": "charlie@example.com", "responseStatus": "accepted"},
                    {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
                ]
            },
        )
    
    def test_returns_dict(self):
        """
        get_top_contacts() should return a dict.
        """
        result = get_top_contacts()
        self.assertIsInstance(result, dict)
    
    def test_returns_correct_structure(self):
        """
        Result should have top_contacts and all_contacts.
        """
        result = get_top_contacts()
        
        self.assertIn("top_contacts", result)
        self.assertIn("all_contacts", result)
    
    def test_top_contacts_structure(self):
        """
        Each contact should have email, meeting_count, total_minutes, total_hours.
        """
        result = get_top_contacts()
        
        if result["top_contacts"]:
            contact = result["top_contacts"][0]
            self.assertIn("email", contact)
            self.assertIn("meeting_count", contact)
            self.assertIn("total_minutes", contact)
            self.assertIn("total_hours", contact)
    
    def test_alice_is_top_contact(self):
        """
        Alice should be the top contact (2 meetings).
        """
        result = get_top_contacts()
        
        self.assertGreater(len(result["top_contacts"]), 0)
        top_contact = result["top_contacts"][0]
        self.assertEqual(top_contact["email"], "alice@example.com")
        self.assertEqual(top_contact["meeting_count"], 2)
        self.assertEqual(top_contact["total_minutes"], 120)
    
    def test_excludes_self(self):
        """
        The calendar owner (self) should not be in the contacts list.
        """
        result = get_top_contacts()
        
        emails = [c["email"] for c in result["all_contacts"]]
        self.assertNotIn("me@example.com", emails)
    
    def test_respects_limit(self):
        """
        Should return only the specified number of top contacts.
        """
        result = get_top_contacts(limit=2)
        
        # We have 3 contacts, but limit is 2
        self.assertLessEqual(len(result["top_contacts"]), 2)
    
    def test_sorted_by_meeting_count(self):
        """
        Contacts should be sorted by meeting_count descending.
        """
        result = get_top_contacts()
        
        counts = [c["meeting_count"] for c in result["top_contacts"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
    
    def test_empty_results(self):
        """
        Should return empty lists when no events.
        """
        CalendarEvent.objects.all().delete()
        
        result = get_top_contacts()
        
        self.assertEqual(result["top_contacts"], [])
        self.assertEqual(result["all_contacts"], [])


class TopContactsViewTests(APITestCase):
    """
    Test cases for the TopContactsView API endpoint.
    """
    
    def setUp(self):
        """
        Create test events with attendees.
        """
        self.now = timezone.now()
        one_week_ago = self.now - timedelta(days=7)
        
        CalendarEvent.objects.create(
            google_event_id="api-contacts-1",
            calendar_id="primary",
            summary="API Test Meeting",
            start_time=one_week_ago,
            end_time=one_week_ago + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
            raw_json={
                "id": "api-contacts-1",
                "attendees": [
                    {"email": "test@example.com", "responseStatus": "accepted"},
                    {"email": "me@example.com", "self": True},
                ]
            },
        )
        
        self.url = reverse("calaudit:top-contacts")
    
    def test_get_returns_200(self):
        """
        GET request should return 200 OK.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
    
    def test_response_structure(self):
        """
        Response should have metric, period, top_contacts, and all_contacts.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIn("metric", data)
        self.assertIn("period", data)
        self.assertIn("top_contacts", data)
        self.assertIn("all_contacts", data)
        
        self.assertEqual(data["metric"], "top_contacts")
    
    def test_default_period(self):
        """
        Default period should be last_3_months.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["period"], "last_3_months")
    
    def test_months_parameter(self):
        """
        months query parameter should change the period.
        """
        response = self.client.get(self.url, {"months": 6})
        data = response.json()
        
        self.assertEqual(data["period"], "last_6_months")
    
    def test_limit_parameter(self):
        """
        limit query parameter should limit top_contacts.
        """
        response = self.client.get(self.url, {"limit": 5})
        data = response.json()
        
        # Should have at most 5 in top_contacts
        self.assertLessEqual(len(data["top_contacts"]), 5)
    
    def test_contains_test_contact(self):
        """
        Response should contain the test contact.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        emails = [c["email"] for c in data["all_contacts"]]
        self.assertIn("test@example.com", emails)
    
    def test_empty_database(self):
        """
        Should return empty lists when no events.
        """
        CalendarEvent.objects.all().delete()
        
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["top_contacts"], [])
        self.assertEqual(data["all_contacts"], [])


class GetInterviewTimeTests(TestCase):
    """
    Test cases for the get_interview_time() query function.
    """
    
    def setUp(self):
        """
        Create test events with various summaries.
        """
        self.now = timezone.now()
        one_week_ago = self.now - timedelta(days=7)
        
        # Interview event
        CalendarEvent.objects.create(
            google_event_id="interview-1",
            calendar_id="primary",
            summary="Interview - John Doe",
            start_time=one_week_ago,
            end_time=one_week_ago + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
        
        # Phone screen event
        CalendarEvent.objects.create(
            google_event_id="interview-2",
            calendar_id="primary",
            summary="Phone Screen with Candidate",
            start_time=one_week_ago + timedelta(hours=2),
            end_time=one_week_ago + timedelta(hours=2, minutes=30),
            duration_minutes=30,
            all_day=False,
            status="confirmed",
        )
        
        # Regular meeting (should not match)
        CalendarEvent.objects.create(
            google_event_id="regular-1",
            calendar_id="primary",
            summary="Team Standup",
            start_time=one_week_ago + timedelta(hours=3),
            end_time=one_week_ago + timedelta(hours=3, minutes=15),
            duration_minutes=15,
            all_day=False,
            status="confirmed",
        )
    
    def test_returns_dict(self):
        """
        get_interview_time() should return a dict.
        """
        result = get_interview_time()
        self.assertIsInstance(result, dict)
    
    def test_returns_correct_structure(self):
        """
        Result should have expected keys.
        """
        result = get_interview_time()
        
        self.assertIn("total_meetings", result)
        self.assertIn("total_minutes", result)
        self.assertIn("total_hours", result)
        self.assertIn("monthly_breakdown", result)
        self.assertIn("matching_events", result)
    
    def test_matches_interview_keyword(self):
        """
        Should match events with 'Interview' in summary.
        """
        result = get_interview_time()
        
        summaries = [e["summary"] for e in result["matching_events"]]
        self.assertTrue(any("Interview" in s for s in summaries))
    
    def test_matches_phone_screen_keyword(self):
        """
        Should match events with 'Phone Screen' in summary.
        """
        result = get_interview_time()
        
        summaries = [e["summary"] for e in result["matching_events"]]
        self.assertTrue(any("Phone Screen" in s for s in summaries))
    
    def test_excludes_non_interview_events(self):
        """
        Should not include events without interview keywords.
        """
        result = get_interview_time()
        
        summaries = [e["summary"] for e in result["matching_events"]]
        self.assertNotIn("Team Standup", summaries)
    
    def test_calculates_correct_total(self):
        """
        Total should sum durations of matched events only.
        """
        result = get_interview_time()
        
        # Interview (60) + Phone Screen (30) = 90
        self.assertEqual(result["total_meetings"], 2)
        self.assertEqual(result["total_minutes"], 90)
    
    def test_case_insensitive_matching(self):
        """
        Keyword matching should be case-insensitive.
        """
        CalendarEvent.objects.create(
            google_event_id="interview-case",
            calendar_id="primary",
            summary="INTERVIEW with Jane",  # uppercase
            start_time=self.now - timedelta(days=1),
            end_time=self.now - timedelta(days=1) + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
        
        result = get_interview_time()
        
        summaries = [e["summary"] for e in result["matching_events"]]
        self.assertIn("INTERVIEW with Jane", summaries)
    
    def test_empty_results(self):
        """
        Should return zeros when no matching events.
        """
        CalendarEvent.objects.all().delete()
        
        result = get_interview_time()
        
        self.assertEqual(result["total_meetings"], 0)
        self.assertEqual(result["total_minutes"], 0)
        self.assertEqual(result["matching_events"], [])


class InterviewTimeViewTests(APITestCase):
    """
    Test cases for the InterviewTimeView API endpoint.
    """
    
    def setUp(self):
        """
        Create test interview events.
        """
        self.now = timezone.now()
        one_week_ago = self.now - timedelta(days=7)
        
        CalendarEvent.objects.create(
            google_event_id="api-interview-1",
            calendar_id="primary",
            summary="Technical Interview",
            start_time=one_week_ago,
            end_time=one_week_ago + timedelta(hours=1),
            duration_minutes=60,
            all_day=False,
            status="confirmed",
        )
        
        self.url = reverse("calaudit:interview-time")
    
    def test_get_returns_200(self):
        """
        GET request should return 200 OK.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
    
    def test_response_structure(self):
        """
        Response should have expected keys.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertIn("metric", data)
        self.assertIn("period", data)
        self.assertIn("total_meetings", data)
        self.assertIn("total_minutes", data)
        self.assertIn("total_hours", data)
        self.assertIn("monthly_breakdown", data)
        self.assertIn("matching_events", data)
        
        self.assertEqual(data["metric"], "interview_time")
    
    def test_default_period(self):
        """
        Default period should be last_3_months.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["period"], "last_3_months")
    
    def test_months_parameter(self):
        """
        months query parameter should change the period.
        """
        response = self.client.get(self.url, {"months": 6})
        data = response.json()
        
        self.assertEqual(data["period"], "last_6_months")
    
    def test_finds_interview_event(self):
        """
        Should find the test interview event.
        """
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertGreaterEqual(data["total_meetings"], 1)
        summaries = [e["summary"] for e in data["matching_events"]]
        self.assertIn("Technical Interview", summaries)
    
    def test_empty_database(self):
        """
        Should return zeros when no events.
        """
        CalendarEvent.objects.all().delete()
        
        response = self.client.get(self.url)
        data = response.json()
        
        self.assertEqual(data["total_meetings"], 0)
        self.assertEqual(data["total_minutes"], 0)
        self.assertEqual(data["matching_events"], [])
