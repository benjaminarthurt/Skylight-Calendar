# skylight-calendar

An unofficial Python client for the [Skylight](https://www.ourskylight.com) family calendar.
It covers what the Skylight app shows: the **calendar**, **profiles** (family members),
**lists** (grocery / to-do), **chores & tasks**, **rewards** and **meal planning**.

Built to be dropped into other projects: an AI agent harness, a Home Assistant
integration, a cron job. One login is saved on disk and shared by all of them.

> Skylight does not publish an API. This talks to the private one its web and
> mobile apps use (`app.ourskylight.com/api`), reconstructed from community work
> (see [Credits](#credits)). It can break whenever Skylight changes their app.

## Install

```bash
pip install git+https://github.com/benjaminarthurt/Skylight-Calendar
# or, from a checkout
pip install -e .
```

Python 3.11+, with **no required dependencies**: the sync client and the login run
on the standard library. If `httpx` is installed it is used instead, and
`AsyncSkylightClient` needs it:

```bash
pip install 'skylight-calendar[httpx] @ git+https://github.com/benjaminarthurt/Skylight-Calendar'
```

## Log in once

```bash
export SKYLIGHT_EMAIL=you@example.com
skylight login            # prompts for the password, saves a session
skylight whoami
```

The session (access + refresh token, never the password) is written to
`~/.config/skylight-calendar/credentials.json` (or `$SKYLIGHT_TOKEN_FILE`) with
owner-only permissions. Tokens are refreshed automatically; if the refresh ever
fails and `SKYLIGHT_PASSWORD` is set, the client logs in again on its own.

Environment variables understood by `SkylightClient.from_env()` and the CLI:

| Variable | Purpose |
| --- | --- |
| `SKYLIGHT_EMAIL`, `SKYLIGHT_PASSWORD` | Used to log in when there is no saved session |
| `SKYLIGHT_ACCESS_TOKEN` | Use a fixed bearer token instead (no refresh) |
| `SKYLIGHT_FRAME_ID` | Which frame (household) to use; defaults to the first one |
| `SKYLIGHT_TIMEZONE` | IANA zone for calendar queries; defaults to the frame's |
| `SKYLIGHT_TOKEN_FILE` | Where the session is saved |

## CLI

```bash
skylight events --days 7          # upcoming calendar
skylight profiles                 # family members and their ids
skylight lists                    # pending items on every list
skylight lists --add Milk Eggs    # add to the grocery list
skylight chores                   # today's chores
skylight chores --complete 777-2026-01-05-0600
skylight rewards                  # point balances and rewards
skylight meals --days 7           # meal plan
skylight raw GET /frames/{frame}/nudges   # any endpoint, raw JSON
```

Add `--json` for machine-readable output.

## Python

```python
from datetime import date, datetime
from skylight_calendar import SkylightClient

client = SkylightClient.from_env()          # saved session, or SKYLIGHT_EMAIL/PASSWORD

# Calendar
for event in client.list_events(days=7):
    print(event.starts_at, event.summary, event.profile_ids)

kayla = client.find_profile("Kayla")
client.create_event("Dentist", datetime(2026, 1, 5, 8, 0), profile_ids=[kayla.id], location="Downtown")
#  naive datetimes are wall-clock time in the frame's timezone; ends_at defaults to +1h

# Lists
grocery = client.grocery_list()
client.add_list_item(grocery.id, "Bread")
for item in grocery.pending_items:
    print(item.label)

# Chores
for chore in client.list_chores():           # today
    print("x" if chore.done else " ", chore.summary, chore.profile_id)
client.complete_chore(chore.id)              # occurrence ids are handled for you
client.create_chore("Dishes", profile_ids=[kayla.id], reward_points=2)

# Rewards
balances = {p.profile_id: p.current_point_balance for p in client.get_reward_points()}
client.redeem_reward(reward_id, profile_id=kayla.id)

# Meals
plan = client.get_meal_plan(days=7)
for sitting in plan.on(date.today()):
    print(plan.category_label(sitting), sitting.summary or plan.recipe_for(sitting).summary)
dinner = next(c for c in client.list_meal_categories() if c.label == "Dinner")
client.create_meal_sitting(date.today(), dinner.id, summary="Tacos")
```

Every model keeps the untouched API resource in `.raw` and exposes it via
`.attributes`, so fields this package does not model are still reachable.
`model.to_dict()` gives JSON-friendly output for agents and logs.

Other constructors:

```python
SkylightClient(email=..., password=..., token_store=FileTokenStore("/srv/app/skylight.json"))
SkylightClient(access_token="...")                         # fixed token, e.g. from a secret store
SkylightClient(credentials=Credentials(access_token=..., refresh_token=...))
```

### Without httpx

With `httpx` absent, `SkylightClient` uses `StdlibClient`, a small `urllib`
transport (cookies kept, redirects returned, not followed). Pass one yourself to
refuse to send a token anywhere but Skylight, whatever URL the client is given:

```python
from skylight_calendar import SkylightClient, StdlibClient

client = SkylightClient(credentials=creds, http=StdlibClient(allowed_hosts={"app.ourskylight.com"}))
```

A refused host, a timeout or a dropped connection raises `SkylightError`.

### Async

`AsyncSkylightClient` has the same methods, all awaitable, and accepts a shared
`httpx.AsyncClient`:

```python
from skylight_calendar import AsyncSkylightClient

async with AsyncSkylightClient.from_env() as client:
    events = await client.list_events(days=1)
```

### In an AI agent harness

`examples/agent_tools.py` wraps the client in plain functions that return dicts
(`get_upcoming_events`, `add_event`, `get_chores`, `complete_chore`,
`get_shopping_list`, `add_to_shopping_list`, `get_meal_plan`, `get_reward_points`).
Register those as tools in whatever framework you use; they only need
`skylight login` to have been run on the machine.

### In Home Assistant

Use `AsyncSkylightClient` with Home Assistant's shared session and store the
tokens in the config entry:

```python
from homeassistant.helpers.httpx_client import get_async_client
from skylight_calendar import AsyncSkylightClient, Credentials, MemoryTokenStore

creds = Credentials.from_dict(entry.data["credentials"])
client = AsyncSkylightClient(credentials=creds, token_store=MemoryTokenStore(creds), http=get_async_client(hass))
```

For the config flow, `skylight_calendar.BrowserLogin` gives you an authorize URL
to show the user and exchanges the URL they are redirected to, so your
integration never sees their password. `client.credentials` holds the latest
(rotated) tokens; persist them after each refresh.

## What is covered

| Area | Read | Write |
| --- | --- | --- |
| Account / frames / devices | `get_user`, `list_frames`, `get_frame`, `list_devices` | `update_device` (brightness, sleep…) |
| Profiles | `list_profiles`, `get_profile`, `find_profile` | `create_profile`, `update_profile`, `delete_profile` |
| Calendar | `list_events`, `list_source_calendars` | `create_event`, `update_event`, `delete_event` |
| Lists | `list_lists`, `get_list`, `find_list`, `grocery_list`, `todo_list` | `create_list`, `update_list`, `delete_list`, `add_list_item`, `update_list_item`, `complete_list_item`, `delete_list_item(s)` |
| Chores | `list_chores`, `list_task_box_items` | `create_chore`, `update_chore`, `complete_chore`, `uncomplete_chore`, `delete_chore`, `create_task_box_item`, `delete_task_box_item` |
| Rewards | `list_rewards`, `get_reward_points` | `create_reward`, `update_reward`, `delete_reward`, `redeem_reward`, `unredeem_reward` |
| Meals | `list_meal_categories`, `list_recipes`, `get_recipe`, `get_meal_plan` | `create_recipe`, `update_recipe`, `delete_recipe`, `add_recipe_to_grocery_list`, `create_meal_sitting`, `update_meal_sitting`, `delete_meal_sitting` |

Anything else: `client.request("GET", "/frames/123/nudges")` returns raw JSON,
and `skylight_calendar._ops` shows how each request is built if you want to add
an endpoint properly.

Request bodies marked *captured* in `_ops.py` were observed from the Skylight
web app; those marked *inferred* were reconstructed from other clients. A
`SkylightValidationError` (HTTP 422) includes the payload that was sent so an
inferred shape can be corrected from a real capture.

## Notes on the API

- Everything is scoped to a *frame* (a household). The client finds your first
  frame and its timezone automatically.
- Family members are "categories" on the wire; this package calls them profiles.
- Recurring chores are listed once per occurrence with ids like
  `<series>-<YYYY-MM-DD>-<HHMM>`; `complete_chore` splits those for you.
  Editing a chore makes Skylight re-key it, so use the id it returns.
- Rewards and chores are created once per assigned profile.
- Skylight reads timestamps without an offset as UTC, so the client localises
  naive datetimes to the frame's timezone before sending.
- Date ranges in this package are end-inclusive; the API's `date_max` is
  exclusive and the conversion is handled for you.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Tests run against a fake Skylight server (`tests/conftest.py`); no account needed.

## Credits

The API surface was pieced together from these community projects:
[pyskylight](https://github.com/joshuaswarren/pyskylight),
[skylight-api (OpenAPI spec)](https://github.com/TheEagleByte/skylight-api),
[skylight-mcp](https://github.com/dwooods/skylight-mcp),
[devinslick/skylight-api](https://github.com/devinslick/skylight-api),
[ha-skylight](https://github.com/dknowles2/ha-skylight) and
[dknowles2's REST notes](https://gist.github.com/dknowles2/b8eab833eb23eb388c3d78999a3565f8).

Not affiliated with Skylight. MIT licensed.
