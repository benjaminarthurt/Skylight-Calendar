"""A fake Skylight server built on ``httpx.MockTransport``."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

BASE = "https://app.ourskylight.com"
CALLBACK = "https://ourskylight.com/welcome"

LOGIN_HTML = '<html><form><input type="hidden" name="authenticity_token" value="csrf-123" /></form></html>'

FRAME = {
    "id": "5455113",
    "type": "frame",
    "attributes": {"name": "smith-7772", "household_name": "The Smiths", "timezone": "America/Chicago"},
}
PROFILES = [
    {"id": "13624117", "type": "category_detail", "attributes": {"label": "Kayla", "color": "#915EA1", "linked_to_profile": True, "selected_for_chore_chart": True}},
    {"id": "13600771", "type": "category_detail", "attributes": {"label": "Garrett", "color": "#CB434C", "linked_to_profile": True, "selected_for_chore_chart": True}},
    {"id": "99", "type": "category", "attributes": {"label": "Family", "color": "#000000", "linked_to_profile": False, "selected_for_chore_chart": False}},
]
EVENT = {
    "id": "5355662012-1767018600",
    "type": "calendar_event",
    "attributes": {
        "summary": "Kaha 1:1",
        "starts_at": "2025-12-29T09:30:00.000-05:00",
        "ends_at": "2025-12-29T10:00:00.000-05:00",
        "all_day": False,
        "recurring": True,
        "rrule": ["RRULE:FREQ=WEEKLY;WKST=MO"],
        "timezone": "America/New_York",
        "source": "google",
        "status": "approved",
        "editable": True,
        "invited_emails": [],
        "calendar_id": "user@example.com",
    },
    "relationships": {
        "calendar_account": {"data": {"id": "1570313", "type": "calendar_account"}},
        "categories": {"data": [{"id": "13600771", "type": "category"}]},
    },
}
LISTS = {
    "data": [
        {
            "id": "4493487",
            "type": "list",
            "attributes": {"label": "Grocery List", "kind": "shopping", "color": "#B6E085", "default_grocery_list": True, "hide_on_device": False},
            "relationships": {"list_items": {"data": [{"id": "2", "type": "list_item"}, {"id": "1", "type": "list_item"}]}},
        },
        {
            "id": "4493488",
            "type": "list",
            "attributes": {"label": "To-Do List", "kind": "to_do", "color": "#A8D4D3", "default_grocery_list": False},
            "relationships": {"list_items": {"data": [{"id": "3", "type": "list_item"}]}},
        },
    ],
    "included": [
        {"id": "1", "type": "list_item", "attributes": {"label": "Eggs", "position": 1, "section": None, "status": "pending", "created_at": "2025-12-29T18:33:24.183Z"}, "relationships": {"list": {"data": {"id": "4493487", "type": "list"}}}},
        {"id": "2", "type": "list_item", "attributes": {"label": "Milk", "position": 2, "section": "Dairy", "status": "completed"}, "relationships": {"list": {"data": {"id": "4493487", "type": "list"}}}},
        {"id": "3", "type": "list_item", "attributes": {"label": "Call plumber", "position": 1, "status": "pending"}, "relationships": {"list": {"data": {"id": "4493488", "type": "list"}}}},
    ],
}
CHORES = [
    {
        "id": "55900629",
        "type": "chore",
        "attributes": {"summary": "Schedule Rue Nail Trim", "status": "pending", "start": "2025-12-29", "start_time": None, "recurring": False, "routine": False, "emoji_icon": "🐻", "reward_points": None, "position": 1, "group": "55900629"},
        "relationships": {"category": {"data": {"id": "13624117", "type": "category"}}},
    },
    {
        "id": "777-2025-12-29-0600",
        "type": "chore",
        "attributes": {"summary": "Make bed", "status": "complete", "start": "2025-12-29", "start_time": "06:00", "completed_on": "2025-12-29", "recurring": True, "routine": True, "recurrence_set": ["RRULE:FREQ=WEEKLY;INTERVAL=1;WKST=SU;BYHOUR=6;BYDAY=MO,TU"], "reward_points": 2},
        "relationships": {"category": {"data": {"id": "13600771", "type": "category"}}},
    },
]
REWARDS = [
    {"id": "5948363", "type": "reward", "attributes": {"name": "Ice cream", "description": "A scoop", "emoji_icon": "🍦", "point_value": 3, "redeemed_at": None, "respawn_on_redemption": True}, "relationships": {"category": {"data": {"id": "13600771", "type": "category"}}}},
]
REWARD_POINTS = [
    {"category_id": 13624117, "current_point_balance": 4, "lifetime_points_earned": 10},
    {"category_id": 13600771, "current_point_balance": 0, "lifetime_points_earned": 0},
]
MEALS = {
    "data": [
        {
            "id": "22109393",
            "type": "meal_sitting",
            "attributes": {"summary": "Bagels", "instances": ["2025-12-29"], "note": "", "recurring": False, "rrule": None},
            "relationships": {"meal_category": {"data": {"id": "6353078", "type": "meal_category"}}, "meal_recipe": {"data": {"id": "45017219", "type": "meal_recipe"}}},
        }
    ],
    "included": [
        {"id": "6353078", "type": "meal_category", "attributes": {"color": "#A8D4D3", "enabled": True, "label": "Breakfast", "position": 0}},
        {"id": "45017219", "type": "meal_recipe", "attributes": {"summary": "Bagels", "description": "Toast them"}, "relationships": {"meal_category": {"data": {"id": "6353078", "type": "meal_category"}}}},
    ],
}


@dataclass
class FakeSkylight:
    """Records requests and answers like app.ourskylight.com."""

    password: str = "hunter2"
    access_token: str = "access-1"
    refresh_token: str = "refresh-1"
    #: Tokens the API accepts. Add to it to simulate rotation.
    valid_tokens: set[str] = field(default_factory=lambda: {"access-1"})
    requests: list[httpx.Request] = field(default_factory=list)
    token_requests: list[dict[str, list[str]]] = field(default_factory=list)
    issued: int = 0

    # ---- helpers
    def api_calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.requests if r.url.path.startswith("/api/")]

    def last_json(self) -> Any:
        for r in reversed(self.requests):
            if r.content:
                return json.loads(r.content)
        return None

    def _issue(self) -> dict[str, Any]:
        self.issued += 1
        token = f"access-{self.issued}" if self.issued > 1 else self.access_token
        refresh = f"refresh-{self.issued}"
        self.valid_tokens.add(token)
        self.refresh_token = refresh
        return {"access_token": token, "refresh_token": refresh, "token_type": "Bearer", "expires_in": 7200, "created_at": int(time.time())}

    # ---- handler
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        query = parse_qs(request.url.query.decode())

        # OAuth / login
        if path == "/oauth/authorize":
            if request.headers.get("cookie") == "skylightcloud_session=authed":
                return httpx.Response(302, headers={"location": f"{CALLBACK}?code=code-xyz&state={query['state'][0]}"})
            return httpx.Response(302, headers={"location": f"/auth/session/new?{request.url.query.decode()}", "set-cookie": "skylightcloud_session=anon; path=/"})
        if path == "/auth/session/new":
            return httpx.Response(200, text=LOGIN_HTML)
        if path == "/auth/session":
            form = parse_qs(request.content.decode())
            if form.get("authenticity_token") != ["csrf-123"]:
                return httpx.Response(422, text="bad csrf")
            if form.get("password") != [self.password]:
                return httpx.Response(200, text=LOGIN_HTML + "Invalid email or password")
            # back through authorize with the original oauth params (we stashed them in the referer-less world: use state from cookie-free query)
            return httpx.Response(302, headers={"location": "/oauth/authorize?client_id=skylight-mobile&state=" + self._state_from(form, request), "set-cookie": "skylightcloud_session=authed; path=/"})
        if path == "/oauth/token":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            grant = form.get("grant_type", [""])[0]
            if grant == "authorization_code":
                if form.get("code") != ["code-xyz"] or not form.get("code_verifier"):
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self._issue())
            if grant == "refresh_token":
                if form.get("refresh_token") != [self.refresh_token]:
                    return httpx.Response(401, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self._issue())
            return httpx.Response(400, json={"error": "unsupported_grant_type"})

        # API
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") not in self.valid_tokens:
            return httpx.Response(401, json={"errors": ["Invalid token"]})
        assert request.headers.get("skylight-api-version"), "missing Skylight-Api-Version"
        return self.api(request, path, query)

    _pending_state: str = ""

    def _state_from(self, form: dict[str, list[str]], request: httpx.Request) -> str:
        return self._pending_state

    def api(self, request: httpx.Request, path: str, query: dict[str, list[str]]) -> httpx.Response:
        m = request.method
        if path == "/api/user":
            return httpx.Response(200, json={"data": {"id": "1", "type": "user", "attributes": {"email": "me@example.com", "first_name": "Ben"}}})
        if path == "/api/frames":
            return httpx.Response(200, json={"data": [FRAME]})
        if path == f"/api/frames/{FRAME['id']}":
            return httpx.Response(200, json={"data": FRAME})
        if path.endswith("/categories") and m == "GET":
            return httpx.Response(200, json={"data": PROFILES})
        if path.endswith("/calendar_events") and m == "GET":
            return httpx.Response(200, json={"data": [EVENT]})
        if path.endswith("/calendar_events") and m == "POST":
            body = json.loads(request.content)
            return httpx.Response(200, json={"data": {**EVENT, "id": "new-1", "attributes": {**EVENT["attributes"], "summary": body["summary"], "starts_at": body["starts_at"], "ends_at": body["ends_at"]}}})
        if "/calendar_events/" in path and m == "PUT":
            return httpx.Response(200, json={"data": EVENT})
        if "/calendar_events/" in path and m == "DELETE":
            return httpx.Response(204)
        if path.endswith("/source_calendars"):
            return httpx.Response(200, json={"data": [{"id": "4754210", "type": "source_calendar", "attributes": {"name": "Work", "enabled": True}}]})
        if path.endswith("/lists") and m == "GET":
            return httpx.Response(200, json=LISTS)
        if path.endswith("/lists/4493487") and m == "GET":
            return httpx.Response(200, json={"data": LISTS["data"][0], "included": LISTS["included"][:2]})
        if path.endswith("/list_items") and m == "POST":
            body = json.loads(request.content)
            return httpx.Response(201, json={"data": {"id": "9", "type": "list_item", "attributes": {"label": body["label"], "status": "pending", "section": body.get("section")}}})
        if "/list_items/" in path and m == "PUT":
            body = json.loads(request.content)
            return httpx.Response(200, json={"data": {"id": path.rsplit("/", 1)[1], "type": "list_item", "attributes": {"label": "Eggs", **body}}})
        if path.endswith("/chores") and m == "GET":
            return httpx.Response(200, json={"data": CHORES, "included": PROFILES[:2]})
        if path.endswith("/chores/create_multiple"):
            body = json.loads(request.content)
            return httpx.Response(201, json={"data": [{**CHORES[0], "id": f"n{i}", "attributes": {**CHORES[0]["attributes"], "summary": body["summary"]}} for i, _ in enumerate(body["category_ids"] or [None])]})
        if path.endswith("/completions"):
            body = json.loads(request.content)
            if "instance_date" not in body:
                return httpx.Response(422, json={"errors": ["instance_date can't be blank"]})
            return httpx.Response(200, json={"data": {**CHORES[1], "attributes": {**CHORES[1]["attributes"], "status": body["status"]}}, "meta": {"reward_points": {"current_point_balance": 6, "lifetime_points_earned": 12}}, "included": [{"type": "habit_tracker", "attributes": {"current_streak": 3, "longest_streak": 5}}]})
        if "/chores/" in path and m == "DELETE":
            return httpx.Response(200, text="")
        if path.endswith("/rewards") and m == "GET":
            return httpx.Response(200, json={"data": REWARDS})
        if path.endswith("/rewards") and m == "POST":
            body = json.loads(request.content)
            return httpx.Response(201, json={"data": [{**REWARDS[0], "id": f"r{i}", "attributes": {**REWARDS[0]["attributes"], "name": body["name"]}} for i, _ in enumerate(body["category_ids"])]})
        if path.endswith("/redeem"):
            return httpx.Response(200, json={"data": {**REWARDS[0], "attributes": {**REWARDS[0]["attributes"], "redeemed_at": "2025-12-29T18:31:45.183Z"}}})
        if path.endswith("/reward_points"):
            return httpx.Response(200, json=REWARD_POINTS)
        if path.endswith("/meals/sittings") and m == "GET":
            return httpx.Response(200, json=MEALS)
        if path.endswith("/meals/sittings") and m == "POST":
            body = json.loads(request.content)
            return httpx.Response(201, json={"data": [{**MEALS["data"][0], "id": "new-sitting", "attributes": {**MEALS["data"][0]["attributes"], "summary": body.get("summary"), "instances": [body["date"]]}}]})
        if "/meals/sittings/" in path and "/instances/" in path and m == "DELETE":
            return httpx.Response(200, json={"data": [], "meta": {"deleted_sitting_ids": [22109393]}})
        if path.endswith("/meals/categories"):
            return httpx.Response(200, json={"data": MEALS["included"][:1]})
        if path.endswith("/meals/recipes") and m == "GET":
            return httpx.Response(200, json={"data": MEALS["included"][1:]})
        if path.endswith("/task_box/items"):
            return httpx.Response(200, json={"data": [{"id": "33536830", "type": "task_box_item", "attributes": {"summary": "Laundry", "routine": False}}]})
        if path.endswith("/devices"):
            return httpx.Response(200, json={"data": [{"id": "d1", "type": "device", "attributes": {"name": "Kitchen", "brightness": 200}}]})
        if path.endswith("/missing"):
            return httpx.Response(404, json={"errors": ["Not found"]})
        if path.endswith("/invalid"):
            return httpx.Response(422, json={"errors": ["Summary can't be blank"]})
        if path.endswith("/slow"):
            return httpx.Response(429, headers={"Retry-After": "7"}, json={})
        return httpx.Response(500, text=f"unhandled {m} {path}")


class _StatefulFake(FakeSkylight):
    """Threads the OAuth ``state`` from the authorize call through the login POST."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/authorize" and "state" in parse_qs(request.url.query.decode()):
            self._pending_state = parse_qs(request.url.query.decode())["state"][0]
        return super().handler(request)


@pytest.fixture
def fake() -> _StatefulFake:
    return _StatefulFake()


@pytest.fixture
def transport(fake: _StatefulFake) -> httpx.MockTransport:
    return httpx.MockTransport(fake.handler)


@pytest.fixture
def http(transport: httpx.MockTransport) -> httpx.Client:
    with httpx.Client(transport=transport) as client:
        yield client


@pytest.fixture
def async_http(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport)
