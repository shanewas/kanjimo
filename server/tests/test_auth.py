import hashlib
import threading
from datetime import timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from conftest import CSRF, T0
from helpers import invite, login, other_client, request_code
from jstudy.auth import _mail_code, _open_session, code_hash


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
    wrong = "00000000" if code != "00000000" else "00000001"
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
    assert r.status_code == 202, "over the cap looks like any other request"
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
        assert guesser.post("/api/auth/verify", json={"email": f"u{i}@example.com", "code": "00000000"}).status_code == 400
    code = request_code(client, "a@example.com")
    r = guesser.post("/api/auth/verify", json={"email": "a@example.com", "code": code})
    assert r.status_code == 429 and r.headers["retry-after"] == "3600"
    assert q("SELECT count(*) AS n FROM verify_attempts")[0]["n"] == 30
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": code}).status_code == 200
    client.app.state.clock.advance(hours=1, seconds=1)
    assert guesser.post("/api/auth/verify", json={"email": "b@example.com", "code": "00000000"}).status_code == 400


def test_concurrent_code_requests_do_not_pass_the_email_cap_together(client, q):
    # Different IPs, so only the per-email limit can serialise the two requests:
    # seeded at 4 of 5, exactly one of the pair may issue a code.
    for _ in range(4):
        request_code(client, "a@example.com")
    barrier = threading.Barrier(2)
    results = []

    def ask(ip):
        c = TestClient(client.app, base_url="https://testserver", client=(ip, 1), headers=CSRF)
        barrier.wait()
        results.append(c.post("/api/auth/code", json={"email": "a@example.com"}).status_code)

    threads = [threading.Thread(target=ask, args=(ip,)) for ip in ("198.51.100.7", "198.51.100.8")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [202, 202], "both callers still get the generic 202"
    assert len(client.app.state.mailer.sent) == 5
    assert q("SELECT count(*) AS n FROM login_codes WHERE email = 'a@example.com'")[0]["n"] == 5


def test_concurrent_verify_attempts_do_not_pass_the_ip_cap_together(client, q):
    q("INSERT INTO verify_attempts (ip, created_at) SELECT '198.51.100.9', %s FROM generate_series(1, 29)", (T0,))
    barrier = threading.Barrier(2)
    responses = []

    def guess():
        c = TestClient(client.app, base_url="https://testserver", client=("198.51.100.9", 1), headers=CSRF)
        barrier.wait()
        responses.append(c.post("/api/auth/verify", json={"email": "a@example.com", "code": "00000000"}))

    threads = [threading.Thread(target=guess) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status_code for r in responses) == [400, 429]
    assert [r.headers["retry-after"] for r in responses if r.status_code == 429] == ["3600"]
    assert q("SELECT count(*) AS n FROM verify_attempts")[0]["n"] == 30


def test_superseded_code_stays_rejected_after_the_new_code_is_used(client):
    first = request_code(client, "a@example.com")
    second = request_code(client, "a@example.com")
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "code": second}).status_code == 200
    r = client.post("/api/auth/verify", json={"email": "a@example.com", "code": first})
    assert r.status_code == 400 and r.json() == {"error": "invalid_code"}


def test_mail_failure_voids_only_the_failed_code(client, q):
    # Two live rows at once (direct rows: the request flow now keeps at most one
    # unused code per email). Failing the first mail must not void the second.
    invite(client, "a@example.com")
    pepper = client.app.state.settings.session_pepper
    ids = {}
    for label, code in (("first", "11111111"), ("second", "22222222")):
        ids[label] = q(
            "INSERT INTO login_codes (email, code_hash, created_at, expires_at) VALUES (%s, %s, %s, %s) RETURNING id",
            ("a@example.com", code_hash(pepper, "a@example.com", code), T0, T0 + timedelta(minutes=10)),
        )[0]["id"]
    client.app.state.mailer.fail = RuntimeError("smtp down")
    _mail_code(client.app.state, "a@example.com", "11111111", T0, ids["first"])
    rows = {row["id"]: row for row in q("SELECT id, used_at FROM login_codes")}
    assert rows[ids["first"]]["used_at"] is not None
    assert rows[ids["second"]]["used_at"] is None
    r = client.post("/api/auth/verify", json={"email": "a@example.com", "code": "22222222"})
    assert r.status_code == 200


def test_concurrent_first_signins_share_one_account(client, q):
    invite(client, "a@example.com")
    barrier = threading.Barrier(2)
    opened, errors = [], []

    def sign_in():
        try:
            with client.app.state.pool.connection() as conn:
                barrier.wait()
                opened.append(_open_session(conn, SimpleNamespace(headers={}), "a@example.com", None, T0))
        except Exception as exc:  # collected and asserted below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=sign_in) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(opened) == 2 and all(o is not None for o in opened)
    assert len({o[0].id for o in opened}) == 1 and opened[0][1] != opened[1][1]
    assert q("SELECT count(*) AS n FROM users")[0]["n"] == 1
    assert q("SELECT count(*) AS n FROM sessions")[0]["n"] == 2


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

