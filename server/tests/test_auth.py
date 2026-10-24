import hashlib

from fastapi.testclient import TestClient

from conftest import CSRF
from helpers import invite, login, other_client, request_code


def test_login_flow_cookie_flags_and_me(client):
    code = request_code(client, "A@Example.com")
    r = client.post("/api/auth/verify", json={"email": "a@example.com", "code": code})
    assert r.status_code == 200
    assert r.json() == {"user": {"id": 1, "email": "a@example.com", "admin": False}}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-jstudy=")
    for flag in ("Secure", "HttpOnly", "SameSite=lax", "Path=/", "Max-Age=2592000"):
        assert flag in cookie, cookie
    me = client.get("/api/me")
    assert me.status_code == 200 and me.json() == {"user": {"id": 1, "email": "a@example.com", "admin": False}}
    assert client.app.state.mailer.sent[-1][0] == "a@example.com"


def test_n1_no_cookie_is_401(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/progress").status_code == 401
    r = client.put("/api/progress", json={"store": {}}, headers={"If-Match": '"0"'})
    assert r.status_code == 401 and r.json() == {"error": "login_required"}


def test_n2_random_token_and_expired_session_is_swept(client, q):
    client.cookies.set("__Host-jstudy", "x" * 43)
    assert client.get("/api/me").status_code == 401
    client.cookies.clear()
    login(client)
    assert q("SELECT count(*) AS n FROM sessions")[0]["n"] == 1
    client.app.state.clock.advance(days=31)
    assert client.get("/api/me").status_code == 401
    assert q("SELECT count(*) AS n FROM sessions")[0]["n"] == 0


def test_n3_logout_invalidates_cookie(client):
    login(client)
    token = client.cookies.get("__Host-jstudy")
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("__Host-jstudy", token)
    assert client.get("/api/me").status_code == 401


def test_logout_accepts_an_empty_json_body(client):
    login(client)
    second = other_client(client)
    login(second)
    assert client.post("/api/auth/logout", json={}).status_code == 204
    assert client.get("/api/me").status_code == 401
    assert second.get("/api/me").status_code == 200, "an empty body logs out this session only"
    assert client.post("/api/auth/logout", json={}).status_code == 401


def test_n4_logout_everywhere(client):
    login(client)
    second = other_client(client)
    login(second)
    assert client.get("/api/me").status_code == 200 and second.get("/api/me").status_code == 200
    assert client.post("/api/auth/logout", json={"all": True}).status_code == 204
    assert second.get("/api/me").status_code == 401
    assert client.get("/api/me").status_code == 401


def test_n5_five_wrong_guesses_void_the_code(client):
    code = request_code(client, "a@example.com")
    wrong = "000000" if code != "000000" else "000001"
    for _ in range(5):
        r = client.post("/api/auth/verify", json={"email": "a@example.com", "code": wrong})
        assert r.status_code == 400 and r.json() == {"error": "invalid_code"}
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": code}).status_code == 400


def test_n6_code_expires_after_ten_minutes(client):
    code = request_code(client, "a@example.com")
    client.app.state.clock.advance(minutes=11)
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": code}).status_code == 400


def test_n7_code_is_single_use(client):
    code = request_code(client, "a@example.com")
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": code}).status_code == 200
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": code}).status_code == 400


def test_n8_five_codes_per_email_per_hour(client):
    for _ in range(5):
        request_code(client, "a@example.com")
    r = client.post("/api/auth/code", json={"email": "a@example.com"})
    assert r.status_code == 429
    assert r.json()["error"] == "too_many_requests" and r.json()["retry_after"] > 0
    assert int(r.headers["retry-after"]) == r.json()["retry_after"]
    assert len(client.app.state.mailer.sent) == 5
    client.app.state.clock.advance(hours=1, seconds=1)
    assert client.post("/api/auth/code", json={"email": "a@example.com"}).status_code == 202


def test_n9_twenty_codes_per_ip_per_hour(client):
    for i in range(20):
        request_code(client, f"u{i}@example.com")
    invite(client, "u20@example.com")
    assert client.post("/api/auth/code", json={"email": "u20@example.com"}).status_code == 429
    elsewhere = TestClient(client.app, base_url="https://testserver", client=("198.51.100.7", 1), headers=CSRF)
    assert elsewhere.post("/api/auth/code", json={"email": "u20@example.com"}).status_code == 202


def test_verify_attempts_are_capped_per_verifying_ip(client, q):
    guesser = TestClient(client.app, base_url="https://testserver", client=("198.51.100.7", 1), headers=CSRF)
    for i in range(30):
        assert guesser.post("/api/auth/verify", json={"email": f"u{i}@example.com", "code": "000000"}).status_code == 400
    code = request_code(client, "a@example.com")
    r = guesser.post("/api/auth/verify", json={"email": "a@example.com", "code": code})
    assert r.status_code == 429 and r.headers["retry-after"] == "3600"
    assert q("SELECT count(*) AS n FROM verify_attempts")[0]["n"] == 30
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": code}).status_code == 200
    client.app.state.clock.advance(hours=1, seconds=1)
    assert guesser.post("/api/auth/verify", json={"email": "b@example.com", "code": "000000"}).status_code == 400


def test_session_bump_refreshes_the_cookie(client):
    login(client)
    assert "set-cookie" not in client.get("/api/me").headers
    client.app.state.clock.advance(minutes=11)
    r = client.get("/api/me")
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-jstudy=" + client.cookies.get("__Host-jstudy") + ";")
    for flag in ("Secure", "HttpOnly", "SameSite=lax", "Path=/", "Max-Age=2592000"):
        assert flag in cookie, cookie
    assert "set-cookie" not in client.get("/api/me").headers
    client.app.state.clock.advance(minutes=11)
    r = client.post("/api/auth/logout")
    cookies = r.headers.get_list("set-cookie")
    assert r.status_code == 204 and len(cookies) == 1 and "Max-Age=0" in cookies[0], cookies


def test_n31_bad_addresses(client):
    assert client.post("/api/auth/code", json={"email": "not-an-email"}).status_code == 400
    assert client.post("/api/auth/code", json={"email": "a" * 290 + "@x.example"}).status_code == 400
    assert client.post("/api/auth/code", json={"email": 5}).status_code == 400
    r = client.post("/api/auth/code", content=b"nope", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json() == {"error": "bad_request"}


def test_n32_mailer_failure_is_neutral_and_voids_the_code(client, q, caplog):
    invite(client, "a@example.com")
    client.app.state.mailer.fail = RuntimeError("smtp down")
    with caplog.at_level("ERROR", logger="jstudy"):
        r = client.post("/api/auth/code", json={"email": "a@example.com"})
    assert r.status_code == 202 and r.json() == {"ok": True}
    assert any("mail failed" in rec.message for rec in caplog.records)
    rows = q("SELECT used_at FROM login_codes")
    assert len(rows) == 1 and rows[0]["used_at"] is not None


def test_n30_hashes_at_rest_and_logs_hold_no_secrets(client, q, caplog):
    with caplog.at_level("DEBUG"):
        code = request_code(client, "a@example.com")
        assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": code}).status_code == 200
    token = client.cookies.get("__Host-jstudy")
    stored = bytes(q("SELECT code_hash FROM login_codes")[0]["code_hash"])
    assert stored != hashlib.sha256(code.encode()).digest()
    assert stored != hashlib.sha256(f"a@example.com:{code}".encode()).digest()
    session = bytes(q("SELECT token_hash FROM sessions")[0]["token_hash"])
    assert session != token.encode() and session == hashlib.sha256(token.encode()).digest()
    assert code not in caplog.text and token not in caplog.text


def test_failed_guesses_per_email_lock_new_codes_for_a_day(client):
    for _ in range(3):
        code = request_code(client, "a@example.com")
        wrong = "000000" if code != "000000" else "000001"
        for _ in range(5):
            client.post("/api/auth/verify", json={"email": "a@example.com", "code": wrong})
        client.app.state.clock.advance(hours=1, seconds=1)
    r = client.post("/api/auth/code", json={"email": "a@example.com"})
    assert r.status_code == 429 and r.json()["retry_after"] == 86400
    client.app.state.clock.advance(days=1)
    assert client.post("/api/auth/code", json={"email": "a@example.com"}).status_code == 202
