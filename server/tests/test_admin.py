from helpers import login, make_admin, other_client, request_code


def admin_client(client):
    login(client, "boss@example.com")
    make_admin(client, "boss@example.com")
    return client


def test_uninvited_address_gets_no_code(client, q):
    r = client.post("/api/auth/code", json={"email": "stranger@example.com"})
    assert r.status_code == 202 and r.json() == {"ok": True}
    assert client.app.state.mailer.sent == []
    assert q("SELECT count(*) AS n FROM login_codes")[0]["n"] == 0


def test_invite_becomes_account_on_first_sign_in(client, q):
    login(client, "new@example.com")
    assert q("SELECT count(*) AS n FROM invites")[0]["n"] == 0
    assert client.get("/api/me").json()["user"] == {"id": 1, "email": "new@example.com", "admin": False}


def test_revoked_invite_voids_a_code_already_sent(client, q):
    code = request_code(client, "new@example.com")
    q("DELETE FROM invites")
    r = client.post("/api/auth/verify", json={"email": "new@example.com", "code": code})
    assert r.status_code == 403 and r.json() == {"error": "not_invited"}
    assert q("SELECT count(*) AS n FROM users")[0]["n"] == 0


def test_non_admin_is_forbidden(client):
    login(client)
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/invites", json={"email": "x@example.com"}).status_code == 403
    assert client.patch("/api/admin/users/1", json={"disabled": True}).status_code == 403
    client.cookies.clear()
    assert client.get("/api/admin/users").status_code == 401


def test_admin_invites_lists_and_revokes(client):
    admin = admin_client(client)
    r = admin.post("/api/admin/invites", json={"email": " Friend@Example.com "})
    assert r.status_code == 201 and r.json() == {"email": "friend@example.com", "mailed": True}
    to, _, text = admin.app.state.mailer.sent[-1]
    assert to == "friend@example.com" and "https://testserver/app/#/account" in text
    assert admin.post("/api/admin/invites", json={"email": "friend@example.com"}).json()["error"] == "already_invited"
    assert admin.post("/api/admin/invites", json={"email": "boss@example.com"}).json()["error"] == "already_member"
    assert admin.post("/api/admin/invites", json={"email": "nope"}).status_code == 400
    body = admin.get("/api/admin/users").json()
    assert [u["email"] for u in body["users"]] == ["boss@example.com"] and body["users"][0]["admin"] is True
    assert body["invites"][0]["email"] == "friend@example.com"
    assert body["invites"][0]["invited_by"] == "boss@example.com"
    assert admin.request("DELETE", "/api/admin/invites", json={"email": "friend@example.com"}).status_code == 204
    assert admin.get("/api/admin/users").json()["invites"] == []
    sent = len(admin.app.state.mailer.sent)
    assert admin.post("/api/auth/code", json={"email": "friend@example.com"}).status_code == 202
    assert len(admin.app.state.mailer.sent) == sent


def test_disable_ends_sessions_and_blocks_sign_in(client, q):
    member = other_client(client)
    login(member, "m@example.com")
    admin = admin_client(client)
    member_id = q("SELECT id FROM users WHERE email = 'm@example.com'")[0]["id"]
    assert admin.patch(f"/api/admin/users/{member_id}", json={"disabled": True}).status_code == 200
    assert member.get("/api/me").status_code == 401
    assert member.get("/api/auth/check").status_code == 401
    sent = len(member.app.state.mailer.sent)
    assert member.post("/api/auth/code", json={"email": "m@example.com"}).status_code == 202
    assert len(member.app.state.mailer.sent) == sent
    assert admin.patch(f"/api/admin/users/{member_id}", json={"disabled": False}).status_code == 200
    login(member, "m@example.com")
    assert member.get("/api/me").status_code == 200


def test_disabled_user_with_live_code_cannot_finish(client, q):
    code = request_code(client, "m@example.com")
    q("INSERT INTO users (email, disabled_at) VALUES ('m@example.com', now())")
    r = client.post("/api/auth/verify", json={"email": "m@example.com", "code": code})
    assert r.status_code == 403


def test_admin_cannot_touch_self_and_delete_needs_confirm(client, q):
    member = other_client(client)
    login(member, "m@example.com")
    admin = admin_client(client)
    boss_id = q("SELECT id FROM users WHERE email = 'boss@example.com'")[0]["id"]
    member_id = q("SELECT id FROM users WHERE email = 'm@example.com'")[0]["id"]
    assert admin.patch(f"/api/admin/users/{boss_id}", json={"disabled": True}).json() == {"error": "self"}
    assert admin.patch(f"/api/admin/users/{member_id}", json={"disabled": "yes"}).status_code == 400
    assert admin.patch("/api/admin/users/9999", json={"disabled": True}).status_code == 404
    assert admin.request("DELETE", f"/api/admin/users/{member_id}", json={}).status_code == 400
    assert admin.request("DELETE", f"/api/admin/users/{member_id}", json={"confirm": "delete"}).status_code == 204
    assert member.get("/api/me").status_code == 401
    assert q("SELECT count(*) AS n FROM users")[0]["n"] == 1


def test_admin_mutations_need_csrf_header(client, bare):
    admin_client(client)
    bare.cookies.update(client.cookies)
    assert bare.post("/api/admin/invites", json={"email": "x@example.com"}).status_code == 403
