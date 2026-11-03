from __future__ import annotations

import json

import httpx
import pytest

from skylight_calendar import cli


@pytest.fixture
def env(monkeypatch, fake, tmp_path):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "me@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "hunter2")
    monkeypatch.setenv("SKYLIGHT_TOKEN_FILE", str(tmp_path / "creds.json"))
    monkeypatch.setattr(httpx.Client, "__init__", _patched_init(fake))
    return tmp_path


def _patched_init(fake):
    original = httpx.Client.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        original(self, *args, **kwargs)

    return init


def test_login_then_profiles(env, capsys):
    assert cli.main(["login"]) == 0
    out = capsys.readouterr().out
    assert "Logged in as me@example.com" in out and "The Smiths" in out
    assert json.loads((env / "creds.json").read_text())["access_token"] == "access-1"

    assert cli.main(["profiles"]) == 0
    assert "Kayla" in capsys.readouterr().out


def test_json_output(env, capsys):
    assert cli.main(["--json", "events", "--start", "2025-12-29", "--days", "1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["summary"] == "Kaha 1:1"


def test_lists_add_and_show(env, capsys):
    assert cli.main(["lists", "--add", "Bread"]) == 0
    assert "Added 'Bread' to Grocery List" in capsys.readouterr().out
    assert cli.main(["lists", "--all"]) == 0
    out = capsys.readouterr().out
    assert "[x] Milk [Dairy]" in out and "[ ] Eggs" in out


def test_chores_rewards_meals(env, capsys):
    assert cli.main(["chores", "--start", "2025-12-29"]) == 0
    assert "Make bed" in capsys.readouterr().out
    assert cli.main(["chores", "--complete", "777-2025-12-29-0600"]) == 0
    assert "Completed 'Make bed' (balance 6)" in capsys.readouterr().out
    assert cli.main(["rewards"]) == 0
    assert "Ice cream" in capsys.readouterr().out
    assert cli.main(["meals", "--start", "2025-12-29", "--days", "0"]) == 0
    assert "Breakfast  Bagels" in capsys.readouterr().out


def test_error_exit_code(env, capsys):
    assert cli.main(["raw", "GET", "/frames/{frame}/missing"]) == 1
    assert "error:" in capsys.readouterr().err
