"""Expose the family calendar to an LLM agent as plain, JSON-returning tools.

Framework-agnostic: each function takes simple arguments and returns dicts, so
you can wrap them for the Anthropic tool-use API, LangChain, MCP, etc.
Run ``skylight login`` once; the client picks the saved session up from
``~/.config/skylight-calendar/credentials.json``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

from skylight_calendar import SkylightClient


@lru_cache(maxsize=1)
def client() -> SkylightClient:
    return SkylightClient.from_env()


@lru_cache(maxsize=1)
def profile_names() -> dict[str, str]:
    return {p.id: p.label or p.id for p in client().list_profiles()}


def get_upcoming_events(days: int = 7) -> list[dict[str, Any]]:
    """Family calendar events from today for the next ``days`` days."""
    names = profile_names()
    out = []
    for e in client().list_events(days=days):
        out.append(
            {
                "id": e.id,
                "summary": e.summary,
                "starts_at": e.starts_at.isoformat() if e.starts_at else None,
                "ends_at": e.ends_at.isoformat() if e.ends_at else None,
                "all_day": e.all_day,
                "location": e.location,
                "who": [names.get(pid, pid) for pid in e.profile_ids],
            }
        )
    return out


def add_event(summary: str, start: str, end: str | None = None, who: list[str] | None = None, all_day: bool = False) -> dict[str, Any]:
    """Create an event. ``start``/``end`` are ISO strings in the family's local time."""
    c = client()
    ids = [c.find_profile(name).id for name in who or []]
    starts_at = datetime.fromisoformat(start) if not all_day else date.fromisoformat(start[:10])
    ends_at = (datetime.fromisoformat(end) if not all_day else date.fromisoformat(end[:10])) if end else None
    return c.create_event(summary, starts_at, ends_at, all_day=all_day, profile_ids=ids).to_dict()


def get_chores(days: int = 0) -> list[dict[str, Any]]:
    """Chores due today (or over the next ``days`` days) with who they belong to."""
    names = profile_names()
    return [
        {**c.to_dict(), "who": names.get(c.profile_id or "", "up for grabs" if c.up_for_grabs else None)}
        for c in client().list_chores(days=days)
    ]


def complete_chore(chore_id: str) -> dict[str, Any]:
    """Mark a chore (by id from get_chores) as done."""
    return client().complete_chore(chore_id).to_dict()


def get_shopping_list() -> list[dict[str, Any]]:
    return [i.to_dict() for i in client().grocery_list().pending_items]


def add_to_shopping_list(items: list[str]) -> list[dict[str, Any]]:
    c = client()
    lst = c.grocery_list()
    return [c.add_list_item(lst.id, label).to_dict() for label in items]


def get_meal_plan(days: int = 7) -> list[dict[str, Any]]:
    plan = client().get_meal_plan(days=days)
    today = date.today()
    out = []
    for offset in range(days + 1):
        day = today + timedelta(days=offset)
        for s in plan.on(day):
            recipe = plan.recipe_for(s)
            out.append({"date": day.isoformat(), "meal": plan.category_label(s), "what": s.summary or (recipe.summary if recipe else None)})
    return out


def get_reward_points() -> dict[str, int]:
    names = profile_names()
    return {names.get(p.profile_id, p.profile_id): p.current_point_balance for p in client().get_reward_points()}


if __name__ == "__main__":
    import json

    print(json.dumps(get_upcoming_events(3), indent=2))
