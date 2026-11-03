from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from skylight_calendar import (
    AsyncSkylightClient,
    Credentials,
    FileTokenStore,
    MemoryTokenStore,
    SkylightAuthError,
    SkylightClient,
    SkylightConfigError,
    SkylightNotFoundError,
    SkylightRateLimitError,
    SkylightValidationError,
)


@pytest.fixture
def client(fake, http):
    with SkylightClient(email="me@example.com", password="hunter2", token_store=MemoryTokenStore(), http=http) as c:
        yield c


def test_requires_some_credentials():
    with pytest.raises(SkylightConfigError):
        SkylightClient()


def test_logs_in_lazily_and_saves(fake, http):
    store = MemoryTokenStore()
    client = SkylightClient(email="me@example.com", password="hunter2", token_store=store, http=http)
    assert store.load() is None
    user = client.get_user()
    assert user.email == "me@example.com" and user.name == "Ben"
    assert store.load().access_token == "access-1"
    assert fake.api_calls()[-1] == ("GET", "/api/user")


def test_uses_saved_login_without_password(fake, http):
    store = MemoryTokenStore(Credentials(access_token="access-1", refresh_token="refresh-1"))
    client = SkylightClient(token_store=store, http=http)
    assert client.list_frames()[0].display_name == "The Smiths"
    assert not fake.token_requests


def test_default_frame_and_timezone_discovered(client, fake):
    client.list_events(date(2025, 12, 29), date(2025, 12, 31))
    assert client.frame_id == "5455113"
    assert client.timezone == "America/Chicago"
    req = [r for r in fake.requests if r.url.path.endswith("/calendar_events")][-1]
    assert req.url.params["date_min"] == "2025-12-29"
    assert req.url.params["date_max"] == "2026-01-01"  # end inclusive -> exclusive on the wire
    assert req.url.params["timezone"] == "America/Chicago"
    assert req.headers["skylight-api-version"] == "2026-05-01"
    assert req.headers["user-agent"] == "SkylightMobile (web)"


def test_events_parse(client):
    events = client.list_events(date(2025, 12, 29), date(2025, 12, 29))
    e = events[0]
    assert e.summary == "Kaha 1:1"
    assert e.starts_at == datetime(2025, 12, 29, 9, 30, tzinfo=ZoneInfo("America/New_York")) or e.starts_at.utcoffset().total_seconds() == -5 * 3600
    assert e.profile_ids == ["13600771"]
    assert e.calendar_account_id == "1570313"
    assert e.series_id == "5355662012"
    assert e.recurring and e.rrule == ["RRULE:FREQ=WEEKLY;WKST=MO"]
    d = e.to_dict()
    assert d["starts_at"].startswith("2025-12-29T09:30:00")
    assert "raw" not in d


def test_create_event_localises_naive_datetimes(client, fake):
    ev = client.create_event("Dentist", datetime(2026, 1, 5, 8, 0), profile_ids=[13624117], location="Downtown")
    body = fake.last_json()
    assert body["starts_at"] == "2026-01-05T08:00:00.000-06:00"
    assert body["ends_at"] == "2026-01-05T09:00:00.000-06:00"
    assert body["category_ids"] == ["13624117"]
    assert body["timezone"] == "America/Chicago"
    assert body["kind"] == "standard" and body["all_day"] is False
    assert ev.id == "new-1" and ev.summary == "Dentist"


def test_create_all_day_event_from_date(client, fake):
    client.create_event("Holiday", date(2026, 7, 4), all_day=True)
    body = fake.last_json()
    assert body["all_day"] is True
    assert body["starts_at"].startswith("2026-07-04T00:00:00")
    assert body["ends_at"].startswith("2026-07-05T00:00:00")


def test_update_event_maps_profile_ids(client, fake):
    client.update_event("5355662012", summary="Renamed", profile_ids=["1", "2"], starts_at=datetime(2026, 1, 1, 10))
    body = fake.last_json()
    assert body == {"summary": "Renamed", "category_ids": ["1", "2"], "starts_at": "2026-01-01T10:00:00.000-06:00"}
    req = fake.requests[-1]
    assert req.method == "PUT" and req.url.path.endswith("/calendar_events/5355662012")


def test_profiles(client):
    profiles = client.list_profiles()
    assert [p.label for p in profiles] == ["Kayla", "Garrett", "Family"]
    assert client.find_profile("garrett").id == "13600771"
    with pytest.raises(SkylightNotFoundError):
        client.find_profile("Nobody")


def test_lists_with_items(client, fake):
    lists = client.list_lists()
    grocery = lists[0]
    assert grocery.label == "Grocery List" and grocery.is_shopping
    assert [i.label for i in grocery.items] == ["Eggs", "Milk"]  # ordered by position
    assert [i.label for i in grocery.pending_items] == ["Eggs"]
    assert grocery.items[1].completed and grocery.items[1].section == "Dairy"
    assert [i.label for i in lists[1].items] == ["Call plumber"]
    assert client.grocery_list().id == "4493487"
    assert client.todo_list().id == "4493488"
    assert client.find_list("to-do").id == "4493488"

    item = client.add_list_item(grocery.id, "Bread", section="Bakery")
    assert item.label == "Bread" and fake.last_json() == {"label": "Bread", "section": "Bakery"}
    done = client.complete_list_item(grocery.id, "1")
    assert done.completed and fake.last_json() == {"status": "completed"}
    client.complete_list_item(grocery.id, "1", completed=False)
    assert fake.last_json() == {"status": "pending"}


def test_chores_and_completion(client, fake):
    chores = client.list_chores(date(2025, 12, 29))
    req = fake.requests[-1]
    assert req.url.params["after"] == "2025-12-29" and req.url.params["before"] == "2025-12-29"
    assert req.url.params["include_up_for_grabs"] == "true"
    one_off, routine = chores
    assert one_off.profile_id == "13624117" and not one_off.done and one_off.occurrence is None
    assert routine.done and routine.series_id == "777"
    assert routine.occurrence.instance_date == "2025-12-29" and routine.occurrence.instance_time == "06:00"

    result = client.complete_chore(routine.id, completed_on=date(2025, 12, 29))
    req = fake.requests[-1]
    assert req.url.path.endswith("/chores/777/completions")
    assert fake.last_json() == {"status": "complete", "instance_date": "2025-12-29", "instance_time": "06:00", "completed_on": "2025-12-29"}
    assert result.point_balance == 6 and result.current_streak == 3 and result.chore.done

    client.uncomplete_chore(routine.id)
    assert fake.last_json() == {"status": "pending", "instance_date": "2025-12-29", "instance_time": "06:00"}

    # a one-off chore with a start date needs its instance_date
    client.complete_chore(one_off.id, instance_date=one_off.start, completed_on="2025-12-29")
    assert fake.last_json()["instance_date"] == "2025-12-29"
    with pytest.raises(SkylightValidationError, match="instance_date"):
        client.complete_chore(one_off.id)


def test_create_chore(client, fake):
    created = client.create_chore("Dishes", profile_ids=["13624117", "13600771"], start=date(2026, 1, 2), reward_points=3, emoji_icon="🍽️")
    assert len(created) == 2 and created[0].summary == "Dishes"
    body = fake.last_json()
    assert body["category_ids"] == ["13624117", "13600771"]
    assert body["start"] == "2026-01-02" and body["reward_points"] == 3
    assert body["up_for_grabs"] is False and body["recurrence_set"] is None
    with pytest.raises(SkylightConfigError):
        client.create_chore("Nobody's")
    client.delete_chore("777-2025-12-29-0600", apply_to="future")
    assert fake.requests[-1].url.params["apply_to"] == "future"


def test_rewards(client, fake):
    rewards = client.list_rewards()
    assert rewards[0].name == "Ice cream" and rewards[0].profile_id == "13600771" and not rewards[0].redeemed
    points = {p.profile_id: p for p in client.get_reward_points()}
    assert points["13624117"].current_point_balance == 4
    created = client.create_reward("Movie night", 10, profile_ids=["13624117", "13600771"], emoji_icon="🎬")
    assert len(created) == 2
    assert fake.last_json()["category_ids"] == ["13624117", "13600771"]
    redeemed = client.redeem_reward(rewards[0].id, profile_id="13600771")
    assert redeemed.redeemed and fake.last_json() == {"category_id": "13600771"}


def test_meal_plan(client, fake):
    plan = client.get_meal_plan(date(2025, 12, 29), date(2025, 12, 29))
    req = fake.requests[-1]
    assert req.url.params["date_max"] == "2025-12-30" and req.url.params["include"] == "meal_category,meal_recipe"
    sitting = plan.sittings[0]
    assert sitting.date == date(2025, 12, 29) and sitting.kind == "one-off"
    assert plan.category_label(sitting) == "Breakfast"
    assert plan.recipe_for(sitting).summary == "Bagels"
    assert plan.on(date(2025, 12, 29)) == [sitting] and plan.on(date(2025, 12, 30)) == []

    created = client.create_meal_sitting(date(2026, 1, 3), "6353080", summary="Tacos")
    assert created.id == "new-sitting" and created.summary == "Tacos"
    assert fake.last_json() == {"date": "2026-01-03", "meal_category_id": "6353080", "summary": "Tacos"}

    client.create_meal_sitting(date(2026, 1, 3), "6353080", summary="Tacos", repeat_weekly=True)
    body = fake.last_json()
    assert body["rrule"] == "FREQ=WEEKLY;INTERVAL=1;WKST=SU;BYDAY=SA"
    assert fake.requests[-1].headers["skylight-api-version"] == "2026-10-15"

    client.delete_meal_sitting(sitting.id, date(2025, 12, 29))
    req = fake.requests[-1]
    assert req.method == "DELETE" and req.url.path.endswith("/instances/2025-12-29")
    assert req.headers["skylight-api-version"] == "2026-10-15"


def test_401_triggers_refresh_and_retry(fake, http):
    store = MemoryTokenStore(Credentials(access_token="stale", refresh_token="refresh-1"))
    fake.issued = 1  # so the refresh issues access-2
    client = SkylightClient(token_store=store, http=http)
    frames = client.list_frames()
    assert frames and store.load().access_token == "access-2"
    assert [c for c in fake.api_calls()] == [("GET", "/api/frames"), ("GET", "/api/frames")]


def test_401_falls_back_to_password_login(fake, http):
    store = MemoryTokenStore(Credentials(access_token="stale", refresh_token="dead"))
    client = SkylightClient(email="me@example.com", password="hunter2", token_store=store, http=http)
    assert client.list_frames()
    assert store.load().access_token == "access-1"


def test_static_token_401_is_fatal(fake, http):
    client = SkylightClient(access_token="bogus", http=http)
    with pytest.raises(SkylightAuthError):
        client.list_frames()


def test_expired_token_refreshed_before_request(fake, http):
    store = MemoryTokenStore(Credentials(access_token="access-1", refresh_token="refresh-1", expires_at=1))
    fake.issued = 1
    client = SkylightClient(token_store=store, http=http)
    client.list_frames()
    assert fake.token_requests and fake.token_requests[0]["grant_type"] == ["refresh_token"]
    assert fake.requests[-1].headers["authorization"] == "Bearer access-2"


def test_error_mapping(client):
    with pytest.raises(SkylightNotFoundError):
        client.request("GET", "/frames/5455113/missing")
    with pytest.raises(SkylightValidationError, match="Summary can't be blank") as info:
        client.request("POST", "/frames/5455113/invalid", json={"a": 1})
    assert info.value.status == 422 and '"a": 1' in str(info.value)
    with pytest.raises(SkylightRateLimitError) as info2:
        client.request("GET", "/frames/5455113/slow")
    assert info2.value.retry_after == 7


def test_file_token_store_roundtrip(tmp_path):
    store = FileTokenStore(tmp_path / "creds.json")
    assert store.load() is None
    creds = Credentials(access_token="a", refresh_token="r", expires_at=5.0)
    store.save(creds)
    assert (tmp_path / "creds.json").stat().st_mode & 0o777 == 0o600
    assert store.load() == creds
    store.clear()
    assert store.load() is None


def test_from_env(monkeypatch, fake, http, tmp_path):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "me@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "hunter2")
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "5455113")
    monkeypatch.setenv("SKYLIGHT_TIMEZONE", "Europe/London")
    monkeypatch.setenv("SKYLIGHT_TOKEN_FILE", str(tmp_path / "t.json"))
    client = SkylightClient.from_env(http=http)
    client.list_events(date(2026, 1, 1), days=1)
    assert fake.requests[-1].url.params["timezone"] == "Europe/London"
    assert json.loads((tmp_path / "t.json").read_text())["access_token"] == "access-1"


def test_devices_and_task_box(client, fake):
    devices = client.list_devices()
    assert devices[0].name == "Kitchen" and devices[0].attributes["brightness"] == 200
    assert client.list_task_box_items()[0].summary == "Laundry"
    assert client.list_source_calendars()[0].name == "Work"


async def test_async_client(fake, async_http):
    store = MemoryTokenStore()
    async with AsyncSkylightClient(email="me@example.com", password="hunter2", token_store=store, http=async_http) as client:
        events = await client.list_events(date(2025, 12, 29), days=2)
        assert events[0].summary == "Kaha 1:1"
        assert client.timezone == "America/Chicago"
        assert (await client.find_profile("Kayla")).id == "13624117"
        lists = await client.list_lists()
        assert lists[0].items
        result = await client.complete_chore("777-2025-12-29-0600")
        assert result.point_balance == 6
        plan = await client.get_meal_plan(date(2025, 12, 29), days=0)
        assert plan.sittings
        assert store.load().access_token == "access-1"


async def test_async_401_refresh(fake, async_http):
    store = MemoryTokenStore(Credentials(access_token="stale", refresh_token="refresh-1"))
    fake.issued = 1
    async with AsyncSkylightClient(token_store=store, http=async_http) as client:
        assert await client.list_frames()
    assert store.load().access_token == "access-2"
