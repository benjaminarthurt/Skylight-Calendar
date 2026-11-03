"""The standard-library transport, end to end against the same fake Skylight
the httpx tests use, served over a real local socket."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from skylight_calendar import SkylightClient, SkylightError, StdlibClient, TransportError, login
from skylight_calendar import _http


@pytest.fixture
def server(fake):
    """A local HTTP server that hands every request to ``fake.handler``."""

    class Bridge(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            request = httpx.Request(self.command, f"http://{self.headers['Host']}{self.path}", headers=list(self.headers.items()), content=body)
            resp = fake.handler(request)
            resp.read()
            self.send_response(resp.status_code)
            for key, value in resp.headers.multi_items():
                if key.lower() not in ("content-length", "transfer-encoding", "content-encoding"):
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(resp.content)))
            self.end_headers()
            self.wfile.write(resp.content)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve

        def log_message(self, *args: object) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_login_over_the_standard_library(fake, server):
    http = StdlibClient(allow_http=True)
    creds = login("me@example.com", "hunter2", base_url=server, http=http)
    assert creds.access_token == "access-1" and creds.refresh_token == "refresh-1"
    posts = [r for r in fake.requests if r.url.path == "/auth/session"]
    assert "skylightcloud_session=anon" in posts[0].headers.get("cookie", ""), "the login form's session cookie was kept"
    assert fake.token_requests[-1]["grant_type"] == ["authorization_code"]


def test_bad_password_is_an_auth_error(fake, server):
    from skylight_calendar import SkylightAuthError

    with pytest.raises(SkylightAuthError):
        login("me@example.com", "wrong", base_url=server, http=StdlibClient(allow_http=True))


def test_client_calls_params_and_json_bodies(fake, server):
    client = SkylightClient(email="me@example.com", password="hunter2", base_url=server, http=StdlibClient(allow_http=True))
    events = client.list_events(days=3)
    assert events and events[0].summary == "Kaha 1:1"
    get = next(r for r in fake.requests if r.url.path.endswith("/calendar_events") and r.method == "GET")
    assert get.url.params.get("date_min") and get.url.params.get("timezone") == "America/Chicago"
    assert get.headers["authorization"] == "Bearer access-1"
    grocery = client.grocery_list()
    item = client.add_list_item(grocery.id, "Bread")
    assert item.label == "Bread"
    assert fake.last_json()["label"] == "Bread"
    post = [r for r in fake.requests if r.method == "POST" and r.url.path.endswith("/list_items")][-1]
    assert post.headers["content-type"] == "application/json"


def test_an_expired_token_is_refreshed_and_retried(fake, server):
    client = SkylightClient(email="me@example.com", password="hunter2", base_url=server, http=StdlibClient(allow_http=True))
    client.get_user()
    fake.valid_tokens.clear()  # the server forgets access-1: next call 401s, the client refreshes and retries
    assert client.get_user().email == "me@example.com"
    assert fake.token_requests[-1]["grant_type"] == ["refresh_token"]


def test_allowed_hosts_refuse_anything_else(fake, server):
    http = StdlibClient(allow_http=True, allowed_hosts={"app.ourskylight.com"})
    with pytest.raises(TransportError):
        http.get(server + "/api/user")
    client = SkylightClient(access_token="access-1", base_url=server, http=http)
    with pytest.raises(SkylightError, match="not an allowed host"):
        client.get_user()
    assert fake.requests == [], "nothing was sent"


def test_plain_http_is_refused_by_default(server):
    with pytest.raises(TransportError, match="non-https"):
        StdlibClient().get(server + "/api/user")


def test_redirects_are_returned_unless_asked(fake, server):
    http = StdlibClient(allow_http=True)
    resp = http.get(server + "/oauth/authorize?state=s1")
    assert resp.status_code == 302 and resp.headers["location"].startswith("/auth/session/new")
    followed = http.get(server + "/oauth/authorize?state=s1", follow_redirects=True)
    assert followed.status_code == 200 and "authenticity_token" in followed.text


def test_default_client_falls_back_without_httpx(monkeypatch):
    assert isinstance(_http.default_client(5), httpx.Client)
    monkeypatch.setattr(_http, "_httpx", None)
    assert isinstance(_http.default_client(5), StdlibClient)
    from skylight_calendar import SkylightConfigError

    with pytest.raises(SkylightConfigError, match="needs httpx"):
        _http.require_httpx("AsyncSkylightClient")
