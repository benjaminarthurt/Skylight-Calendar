from __future__ import annotations

import time

import pytest

from skylight_calendar import BrowserLogin, Credentials, SkylightAuthError, async_login, async_refresh, login, refresh
from skylight_calendar.auth import _Flow, extract_code, extract_csrf_token, pkce_pair


def test_pkce_pair_is_s256():
    import base64
    import hashlib

    verifier, challenge = pkce_pair()
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_extract_csrf_token_variants():
    assert extract_csrf_token('<input name="authenticity_token" value="a1">') == "a1"
    assert extract_csrf_token("<input value='a2' type='hidden' name='authenticity_token'>") == "a2"
    assert extract_csrf_token('<meta name="csrf-token" content="a3" />') == "a3"
    assert extract_csrf_token("<html></html>") is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("abc", "abc"),
        ("code=abc", "abc"),
        ("https://ourskylight.com/welcome?code=abc&state=s", "abc"),
        ("?code=abc", "abc"),
        ("", None),
    ],
)
def test_extract_code(raw, expected):
    assert extract_code(raw) == expected


def test_flow_state_mismatch_rejected():
    flow = _Flow()
    with pytest.raises(SkylightAuthError, match="state"):
        flow.parse_callback("https://ourskylight.com/welcome?code=x&state=wrong")
    assert flow.parse_callback(f"https://ourskylight.com/welcome?code=x&state={flow.state}") == "x"


def test_login_happy_path(fake, http):
    creds = login("me@example.com", "hunter2", http=http)
    assert creds.access_token == "access-1"
    assert creds.refresh_token == "refresh-1"
    assert creds.expires_at is not None and creds.expires_at > time.time() + 7000
    form = fake.token_requests[-1]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code_verifier"]
    assert form["redirect_uri"] == ["https://ourskylight.com/welcome"]
    assert form["skylight_api_client_device_fingerprint"] == [creds.device_fingerprint]
    # cookies flowed through the login POST
    posts = [r for r in fake.requests if r.url.path == "/auth/session"]
    assert "skylightcloud_session=anon" in posts[0].headers.get("cookie", "")


def test_login_bad_password(fake, http):
    with pytest.raises(SkylightAuthError, match="email or password"):
        login("me@example.com", "nope", http=http)


def test_refresh_rotates(fake, http):
    creds = login("me@example.com", "hunter2", http=http)
    fresh = refresh(creds, http=http)
    assert fresh.access_token == "access-2"
    assert fresh.refresh_token == "refresh-2"
    assert fresh.device_fingerprint == creds.device_fingerprint
    with pytest.raises(SkylightAuthError):
        refresh(creds, http=http)  # old refresh token no longer valid


def test_refresh_without_token():
    with pytest.raises(SkylightAuthError):
        refresh(Credentials(access_token="x"))


async def test_async_login_and_refresh(fake, async_http):
    async with async_http:
        creds = await async_login("me@example.com", "hunter2", http=async_http)
        assert creds.access_token == "access-1"
        fresh = await async_refresh(creds, http=async_http)
        assert fresh.access_token == "access-2"


def test_browser_login(fake, http):
    flow = BrowserLogin()
    assert "code_challenge=" in flow.url and f"state={flow.state}" in flow.url
    creds = flow.exchange(f"https://ourskylight.com/welcome?code=code-xyz&state={flow.state}", http=http)
    assert creds.access_token == "access-1"
    with pytest.raises(SkylightAuthError):
        flow.exchange("https://ourskylight.com/welcome?code=code-xyz&state=bad", http=http)
    assert flow.exchange("code-xyz", http=http).access_token == "access-2"
