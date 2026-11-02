from __future__ import annotations

from datetime import date, datetime, timezone

from skylight_calendar.models import (
    CalendarEvent,
    Chore,
    ChoreOccurrence,
    MealSitting,
    Profile,
    RewardPoints,
    parse_datetime,
    parse_many,
    parse_one,
)


def test_parse_datetime_variants():
    assert parse_datetime("2025-12-29T18:31:45.183Z") == datetime(2025, 12, 29, 18, 31, 45, 183000, tzinfo=timezone.utc)
    assert parse_datetime("2025-12-29") == datetime(2025, 12, 29)
    assert parse_datetime(None) is None and parse_datetime("garbage") is None


def test_occurrence_ids():
    assert ChoreOccurrence.parse("777-2025-12-29-0600") == ChoreOccurrence("777", "2025-12-29", "06:00")
    assert ChoreOccurrence.parse("777-2025-12-29") == ChoreOccurrence("777", "2025-12-29", None)
    assert ChoreOccurrence.parse("55900629") is None
    assert ChoreOccurrence.parse("abc-2025-12-29") is None


def test_parse_one_accepts_bare_resource():
    profile = parse_one({"id": "1", "type": "category", "attributes": {"label": "Kayla"}}, Profile)
    assert profile.label == "Kayla"
    assert parse_many([{"id": "2", "attributes": {}}], Profile)[0].id == "2"


def test_chore_defaults():
    chore = Chore.from_resource({"id": "1", "attributes": {"summary": "X", "status": "completed", "recurrence_set": "RRULE:FREQ=DAILY"}})
    assert chore.done and chore.recurrence_set == ["RRULE:FREQ=DAILY"] and chore.start is None
    assert chore.to_dict()["summary"] == "X"


def test_event_single_category_relationship():
    ev = CalendarEvent.from_resource({"id": "1", "attributes": {"summary": "x", "rrule": "RRULE:FREQ=DAILY"}, "relationships": {"category": {"data": {"id": "9", "type": "category"}}}})
    assert ev.profile_ids == ["9"] and ev.rrule == ["RRULE:FREQ=DAILY"]


def test_reward_points_shapes():
    flat = RewardPoints.from_payload([{"category_id": 1, "current_point_balance": 2, "lifetime_points_earned": 3}])
    wrapped = RewardPoints.from_payload({"data": [{"id": "x", "attributes": {"category_id": "1", "current_point_balance": 2}}]})
    assert flat[0].profile_id == "1" and flat[0].lifetime_points_earned == 3
    assert wrapped[0].profile_id == "1" and wrapped[0].current_point_balance == 2


def test_sitting_kinds():
    series = MealSitting.from_resource({"id": "1", "attributes": {"instances": ["2026-01-01", "2026-01-08"], "rrule": "FREQ=WEEKLY"}})
    detached = MealSitting.from_resource({"id": "2", "attributes": {"date": "2026-01-01", "recurring": True}})
    assert series.kind == "series" and series.dates == [date(2026, 1, 1), date(2026, 1, 8)]
    assert detached.kind == "detached" and detached.date == date(2026, 1, 1)
