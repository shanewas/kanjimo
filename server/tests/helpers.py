"""Request helpers shared by the test modules: login, extra clients, the fake clock."""
import re
from datetime import timedelta

from fastapi.testclient import TestClient

from conftest import CSRF, IP

CODE_RE = re.compile(r"\b(\d{8})\b")


def invite(client, email: str) -> None:
    with client.app.state.pool.connection() as conn:
        conn.execute("INSERT INTO invites (email) VALUES (lower(%s)) ON CONFLICT DO NOTHING", (email,))


def make_admin(client, email: str) -> None:
    with client.app.state.pool.connection() as conn:
        conn.execute("UPDATE users SET is_admin = true WHERE lower(email) = lower(%s)", (email,))


def request_code(client, email: str) -> str:
    invite(client, email)
    r = client.post("/api/auth/code", json={"email": email})
    assert r.status_code == 202, r.text
    return CODE_RE.search(client.app.state.mailer.sent[-1][2]).group(1)


def login(client, email: str = "a@example.com") -> dict:
    code = request_code(client, email)
    r = client.post("/api/auth/verify", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def other_client(client, cookies=None) -> TestClient:
    return TestClient(client.app, base_url=str(client.base_url), client=IP, headers=CSRF, cookies=cookies)


def advance(client, *, days: int = 0, minutes: int = 0) -> None:
    """Moves the fake clock in 10-day steps, touching the session so it slides instead of expiring."""
    clock = client.app.state.clock
    remaining = timedelta(days=days, minutes=minutes)
    step = timedelta(days=10)
    while remaining > step:
        clock.advance(days=10)
        remaining -= step
        assert client.get("/api/me").status_code == 200
    clock.now += remaining
