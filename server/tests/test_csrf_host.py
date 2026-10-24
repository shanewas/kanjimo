import pytest

from helpers import invite, login
from jstudy.config import ConfigError, Settings

STORE = {"version": 4, "items": {}, "days": {}}
ENV = {
    "DATABASE_URL": "postgresql://jstudy_test@127.0.0.1/jstudy_test", "PUBLIC_ORIGIN": "https://study.example",
    "SESSION_PEPPER": "p" * 32,
    "MAIL_FROM": "noreply@study.example", "SMTP_HOST": "smtp.example", "SMTP_USER": "u", "SMTP_PASSWORD": "placeholder",
}


def test_n10_missing_custom_header(client, bare):
    login(client)
    bare.cookies.set("__Host-jstudy", client.cookies.get("__Host-jstudy"))
    r = bare.put("/api/progress", json={"store": STORE}, headers={"If-Match": '"0"'})
    assert r.status_code == 403 and r.json() == {"error": "csrf"}
    assert bare.get("/api/me").status_code == 200


def test_n11_cross_site_markers(client):
    login(client)
    r = client.put("/api/progress", json={"store": STORE}, headers={"If-Match": '"0"', "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.json() == {"error": "csrf"}
    r = client.put("/api/progress", json={"store": STORE}, headers={"If-Match": '"0"', "Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.put("/api/progress", json={"store": STORE},
                   headers={"If-Match": '"0"', "Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_n13_json_content_type_and_dev_headers(dev_client):
    r = dev_client.get("/api/me")
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/json")
    assert r.headers["x-content-type-options"] == "nosniff"
    page = dev_client.get("/app/index.html")
    assert page.status_code == 200
    csp = page.headers["content-security-policy"]
    assert "unsafe-inline" not in csp and csp.startswith("default-src 'none'")
    assert page.headers["cache-control"] == "no-cache"
    assert dev_client.get("/app/").status_code == 200
    assert dev_client.get("/", follow_redirects=False).headers["location"] == "/app/"


def test_n25_wrong_host_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/health").status_code == 200


def test_n26_urls_come_from_public_origin_not_the_request(client):
    forged = {"X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "http", "Forwarded": "host=evil.example"}
    invite(client, "a@example.com")
    assert client.post("/api/auth/code", json={"email": "a@example.com"}, headers=forged).status_code == 202
    text = client.app.state.mailer.sent[-1][2]
    assert "https://testserver/app/#/account" in text and "evil.example" not in text


def test_billing_routes_are_gone(client):
    login(client)
    assert client.post("/api/billing/checkout", json={"price": "monthly"}).status_code == 404
    assert client.post("/api/billing/webhook", content=b"{}").status_code == 404


def test_config_refuses_missing_secret():
    env = dict(ENV)
    del env["SESSION_PEPPER"]
    with pytest.raises(ConfigError, match="SESSION_PEPPER"):
        Settings.from_env(env)
    with pytest.raises(ConfigError, match="SMTP_PASSWORD"):
        Settings.from_env({k: v for k, v in ENV.items() if k != "SMTP_PASSWORD"})
    with pytest.raises(ConfigError, match="too short"):
        Settings.from_env({**ENV, "SESSION_PEPPER": "short"})


def test_config_dev_mode_needs_loopback_origin():
    with pytest.raises(ConfigError, match="loopback"):
        Settings.from_env({**ENV, "JSTUDY_DEV": "1"})
    s = Settings.from_env({**ENV, "JSTUDY_DEV": "1", "PUBLIC_ORIGIN": "http://127.0.0.1:8765", "SMTP_PASSWORD": ""})
    assert s.dev and s.cookie_name == "jstudy" and s.host == "127.0.0.1"


def test_config_prod_needs_https_for_the_host_cookie():
    with pytest.raises(ConfigError, match="https"):
        Settings.from_env({**ENV, "PUBLIC_ORIGIN": "http://study.example"})
    with pytest.raises(ConfigError, match="PUBLIC_ORIGIN"):
        Settings.from_env({**ENV, "PUBLIC_ORIGIN": "https://study.example/app"})
    s = Settings.from_env(ENV)
    assert s.cookie_name == "__Host-jstudy" and s.host == "study.example" and not s.dev
