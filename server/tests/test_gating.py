from conftest import AUDIO_HASH
from helpers import login, request_code


def test_check_endpoint(client):
    assert client.get("/api/auth/check").status_code == 401
    user_id = login(client)["user"]["id"]
    r = client.get("/api/auth/check", headers={"X-Original-URI": "/data/cards/level-01.json"})
    assert r.status_code == 204 and r.headers["x-jstudy-user"] == str(user_id)


def test_check_budget_needs_login(client):
    r = client.get("/api/auth/check-budget", headers={"X-Original-URI": "/data/cards/level-05.json"})
    assert r.status_code == 401 and r.json() == {"error": "login_required"}
    user_id = login(client)["user"]["id"]
    r = client.get("/api/auth/check-budget", headers={"X-Original-URI": "/data/cards/level-05.json"})
    assert r.status_code == 204 and r.headers["x-jstudy-user"] == str(user_id)


def test_dev_gate_every_level_is_open_after_login(dev_client):
    login(dev_client)
    for level in (1, 3, 4, 5, 60):
        r = dev_client.get(f"/data/cards/level-{level:02d}.json")
        assert r.status_code == 200 and r.json() == {"level": level}, level
        assert r.headers["cache-control"] == "private, max-age=86400"
    assert dev_client.get("/data/own/level-04.json").status_code == 200
    assert dev_client.get("/data/search-index.json").status_code == 200
    assert dev_client.get(f"/media/audio/{AUDIO_HASH}.mp3").status_code == 200
    assert dev_client.get("/data/images/cdp-8bc4.svg").status_code == 200
    assert dev_client.get("/data/index.json").headers["cache-control"] == "public, max-age=3600"


def test_n24_daily_budget(client):
    login(client)
    for i in range(300):
        assert client.get("/api/auth/check-budget").status_code == 204, i
    r = client.get("/api/auth/check-budget", headers={"X-Original-URI": "/data/cards/level-09.json"})
    assert r.status_code == 403 and r.headers["x-deny-reason"] == "budget" and r.json() == {"error": "daily_limit"}
    client.app.state.clock.advance(days=1)
    assert client.get("/api/auth/check-budget").status_code == 204


def test_dev_gate_counts_level_files_only(dev_client, q):
    login(dev_client)
    dev_client.get("/data/cards/level-01.json")
    dev_client.get("/data/search-index.json")
    dev_client.get(f"/media/audio/{AUDIO_HASH}.mp3")
    assert q("SELECT hits FROM data_hits")[0]["hits"] == 1


def test_n27_path_tricks_never_reach_the_disk(dev_client):
    login(dev_client)
    assert dev_client.get("/data/../../etc/passwd").status_code in (400, 404)
    assert dev_client.get("/data/%2e%2e/%2e%2e/etc/passwd").status_code in (400, 404)
    assert dev_client.get("/data/cards/level-05.json%00.json").status_code in (400, 404)
    assert dev_client.get("/data/cards/level-05.json::$DATA").status_code in (400, 404)
    assert dev_client.get("/data/cards/level-05.json%3a%3a$DATA").status_code in (400, 404)
    assert dev_client.get("/data/cards/level-61.json").status_code == 404, "on disk but outside the gate"
    assert dev_client.get("/data/cards/level-00.json").status_code == 404
    assert dev_client.get("/data/cards/level-05.json.gz").status_code == 404
    assert dev_client.get("/data/cards/level-5.json").status_code == 404
    assert dev_client.get("/data/anything.json").status_code == 404
    assert dev_client.get("/data/images/../cards/level-05.svg").status_code in (400, 404)
    assert dev_client.get("/data/images/x.svg.json").status_code == 404
    assert dev_client.get("/data/").status_code == 404


def test_n28_media_tricks(dev_client):
    login(dev_client)
    assert dev_client.get("/media/audio/../../app/app.js").status_code in (400, 404)
    assert dev_client.get("/media/audio/ZZ.mp3").status_code == 404
    assert dev_client.get(f"/media/audio/{AUDIO_HASH}.exe").status_code == 404
    assert dev_client.get(f"/media/{AUDIO_HASH}.mp3").status_code == 404


def test_n29_own_file_needs_login(dev_client):
    r = dev_client.get("/data/own/level-04.json")
    assert r.status_code == 401 and r.json() == {"error": "login_required"}
    assert dev_client.get("/data/cards/level-01.json").status_code == 401
    assert dev_client.get("/data/search-index.json").status_code == 401
    assert dev_client.get("/data/images/cdp-8bc4.svg").status_code == 401
    assert dev_client.get("/data/index.json").status_code == 200


def test_dev_cookie_has_no_secure_flag(dev_client):
    code = request_code(dev_client, "a@example.com")
    r = dev_client.post("/api/auth/verify", json={"email": "a@example.com", "code": code})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("jstudy=") and "secure" not in cookie.lower() and "httponly" in cookie.lower()
    assert dev_client.get("/api/me").status_code == 200


def test_nginx_level_locations_mirror_gate_for():
    """nginx's level regex is a hand copy of gate_for; this fails when they drift apart."""
    import re
    from pathlib import Path

    from jstudy.auth import gate_for
    from jstudy.config import MAX_LEVEL

    for conf in sorted((Path(__file__).parents[1] / "deploy").glob("nginx-jstudy-*.conf")):
        text = conf.read_text(encoding="utf-8")
        locations = [(re.compile(m[0]), "budget" if "check-budget" in m[1] else "login")
                     for m in re.findall(r"location ~ (\^/data/\S+) \{([^}]*)\}", text)]
        for kind in ("cards", "items", "levels", "own"):
            for level in range(0, MAX_LEVEL + 2):
                path = f"/data/{kind}/level-{level:02d}.json"
                nginx = [tier for rx, tier in locations if rx.search(path)]
                assert nginx == ([gate_for(path)] if gate_for(path) else []), (conf.name, path)
        assert "proxy_set_header Host $host; }" in text.split("location = /_auth/check-budget")[1], conf.name
        assert text.count("proxy_set_header Host $host;") >= 4, conf.name  # 2 /api/ proxies + 2 auth subrequests
        assert "billing" not in text, conf.name
        # nginx reads an unquoted {n,m} as a block opener and fails `nginx -t`
        assert not re.search(r"location ~ [^\"\s]*\{\d", text), conf.name
        assert "absolute_redirect off;" in text, conf.name  # else redirects leak the loopback port
