from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import T0
from helpers import invite
from jstudy.google import GoogleClient


class FakeGoogle(GoogleClient):
    def __init__(self) -> None:
        super().__init__("cid.apps.googleusercontent.com", "placeholder-not-a-secret")
        self.claims: dict = {}
        self.calls: list[tuple] = []

    def exchange(self, code, verifier, redirect_uri):
        self.calls.append((code, verifier, redirect_uri))
        return dict(self.claims)


@pytest.fixture
def google(app):
    app.state.google = FakeGoogle()
    return app.state.google


def start(client):
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code == 303
    return parse_qs(urlsplit(r.headers["location"]).query)


def good_claims(google, params, **over):
    claims = {"iss": "https://accounts.google.com", "aud": google.client_id, "email": "Me@Gmail.com",
              "email_verified": True, "nonce": params["nonce"][0], "exp": int(T0.timestamp()) + 600}
    claims.update(over)
    return claims


def finish(client, params, code="c0de"):
    return client.get("/api/auth/google/callback", params={"code": code, "state": params["state"][0]},
                      follow_redirects=False)


def test_full_flow_opens_session(client, google, q):
    invite(client, "me@gmail.com")
    params = start(client)
    assert params["redirect_uri"] == ["https://testserver/api/auth/google/callback"]
    assert params["code_challenge_method"] == ["S256"] and params["scope"] == ["openid email"]
    google.claims = good_claims(google, params)
    r = finish(client, params)
    assert r.status_code == 303 and r.headers["location"] == "/app/#/account"
    assert google.calls[0][2] == "https://testserver/api/auth/google/callback"
    me = client.get("/api/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "me@gmail.com"
    assert q("SELECT count(*) AS n FROM users")[0]["n"] == 1


def test_same_email_reuses_code_login_account(client, google, q):
    from helpers import login
    login(client, "me@gmail.com")
    client.cookies.clear()
    params = start(client)
    google.claims = good_claims(google, params)
    finish(client, params)
    assert q("SELECT count(*) AS n FROM users")[0]["n"] == 1


@pytest.mark.parametrize("over, error", [
    ({"aud": "someone-else"}, "google_failed"),
    ({"iss": "https://evil.example"}, "google_failed"),
    ({"nonce": "replayed"}, "google_failed"),
    ({"exp": int(T0.timestamp()) - 1}, "google_failed"),
    ({"email_verified": False}, "google_email"),
    ({"email": "me@corp.example"}, "google_email"),
])
def test_bad_id_token_is_rejected(client, google, over, error):
    params = start(client)
    google.claims = good_claims(google, params, **over)
    r = finish(client, params)
    assert r.headers["location"] == f"/app/#/account?login={error}"
    assert client.get("/api/me").status_code == 401


def test_workspace_domain_is_trusted(client, google):
    invite(client, "me@corp.example")
    params = start(client)
    google.claims = good_claims(google, params, email="me@corp.example", hd="corp.example")
    finish(client, params)
    assert client.get("/api/me").status_code == 200


def test_state_mismatch_and_missing_cookie(client, google):
    params = start(client)
    r = client.get("/api/auth/google/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert r.headers["location"].endswith("login=google_failed") and google.calls == []
    client.cookies.clear()
    r = finish(client, params)
    assert r.headers["location"].endswith("login=google_failed") and google.calls == []


def test_tampered_flow_cookie(client, google):
    start(client)
    name = "__Host-jstudy-g"
    body, _, mac = client.cookies[name].partition(".")
    client.cookies.set(name, body[:-2] + "AA." + mac)
    r = client.get("/api/auth/google/callback", params={"code": "c", "state": "x"}, follow_redirects=False)
    assert r.headers["location"].endswith("login=google_failed")


def test_expired_flow(client, google):
    params = start(client)
    client.app.state.clock.advance(minutes=11)
    google.claims = good_claims(google, params, exp=int(T0.timestamp()) + 3600)
    assert finish(client, params).headers["location"].endswith("login=google_failed")


def test_user_cancelled(client, google):
    params = start(client)
    r = client.get("/api/auth/google/callback", params={"error": "access_denied", "state": params["state"][0]},
                   follow_redirects=False)
    assert r.headers["location"].endswith("login=google_cancelled") and google.calls == []


def test_unconfigured_is_off(client):
    assert client.app.state.google is None
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.headers["location"].endswith("login=google_unavailable")


def test_uninvited_google_account_gets_no_account(client, google, q):
    params = start(client)
    google.claims = good_claims(google, params)
    r = finish(client, params)
    assert r.headers["location"] == "/app/#/account?login=not_invited"
    assert client.get("/api/me").status_code == 401
    assert q("SELECT count(*) AS n FROM users")[0]["n"] == 0
