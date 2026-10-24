"""Hermetic fixtures: a throwaway PostgreSQL per session, tables reset per test, fakes on app.state.

Nothing here can reach a real database: the server is started by pgserver under a random directory
bound to 127.0.0.1 (or JSTUDY_TEST_DATABASE_URL is used), and the database name must end in _test.
"""
import json
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from jstudy.config import Settings
from jstudy.db import migrate
from jstudy.mailer import ListMailer
from jstudy.main import create_app

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
IP = ("203.0.113.5", 50000)
CSRF = {"X-Requested-With": "jstudy"}
AUDIO_HASH = "ab" * 16
TABLES = ("users", "login_codes", "sessions", "progress", "entitlements", "stripe_webhook_inbox",
          "payments", "data_hits", "settings", "verify_attempts", "invites")
REPO = Path(__file__).resolve().parents[2]


def _guard_test_db(url: str) -> None:
    name = urlsplit(url).path.lstrip("/")
    if not name.endswith("_test"):
        pytest.exit(f"refusing to run against database {name!r}: the name must end in _test", returncode=3)


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("JSTUDY_TEST_DATABASE_URL")
    if url:
        _guard_test_db(url)
        yield url
        return
    import pgserver

    base = Path(os.environ.get("JSTUDY_TEST_PGDIR") or REPO.parent / f"{REPO.name}_build" / "pg")
    base.mkdir(parents=True, exist_ok=True)
    pgdata = base / f"pg-{secrets.token_hex(4)}"
    server = pgserver.get_server(pgdata, cleanup_mode="delete")
    try:
        admin = server.get_uri()
        assert urlsplit(admin).hostname == "127.0.0.1", admin
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("CREATE DATABASE jstudy_test")
        url = server.get_uri("jstudy_test")
        _guard_test_db(url)
        yield url
    finally:
        server.cleanup()
        shutil.rmtree(pgdata, ignore_errors=True)


@pytest.fixture(scope="session")
def schema(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        migrate(conn)
    return database_url


def reset_tables(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")


def make_settings(url: str, **over) -> Settings:
    base = dict(
        database_url=url, public_origin="https://testserver", session_pepper="test-pepper-" + "x" * 24,
        mail_from="noreply@testserver", smtp_host="smtp.invalid", smtp_user="placeholder",
        smtp_password="placeholder-not-a-secret",
    )
    base.update(over)
    return Settings(**base)


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


def build_app(url: str, **over):
    app = create_app(make_settings(url, **over), worker=False)
    app.state.mailer = ListMailer()
    app.state.clock = FakeClock()
    return app


@pytest.fixture
def app(schema):
    reset_tables(schema)
    return build_app(schema)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="https://testserver", client=IP, headers=CSRF) as c:
        yield c


@pytest.fixture
def bare(client):
    """Second client on the same app without the CSRF header and without cookies."""
    return TestClient(client.app, base_url="https://testserver", client=IP)


@pytest.fixture
def q(schema):
    def query(statement: str, params=()):
        with psycopg.connect(schema, row_factory=dict_row, autocommit=True) as conn:
            cur = conn.execute(statement, params)
            return cur.fetchall() if cur.description else []
    return query


@pytest.fixture
def dev_client(schema, tmp_path):
    """Dev-mode app serving a small fake frontend and content tree, with the nginx gate table applied in-process."""
    reset_tables(schema)
    static = tmp_path / "app"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>jstudy</title>", encoding="utf-8")
    data = tmp_path / "data"
    for sub in ("cards", "levels", "own", "images"):
        (data / sub).mkdir(parents=True)
    for level in (1, 3, 4, 5, 60, 61):
        (data / "cards" / f"level-{level:02d}.json").write_text(json.dumps({"level": level}), encoding="utf-8")
    (data / "own" / "level-04.json").write_text('{"cards": {}}', encoding="utf-8")
    (data / "index.json").write_text("{}", encoding="utf-8")
    (data / "search-index.json").write_text("{}", encoding="utf-8")
    (data / "images" / "cdp-8bc4.svg").write_text("<svg/>", encoding="utf-8")
    media = tmp_path / "media"
    (media / "audio").mkdir(parents=True)
    (media / "audio" / f"{AUDIO_HASH}.mp3").write_bytes(b"ID3fake")
    app = build_app(schema, public_origin="http://127.0.0.1:8765", dev=True,
                    static_root=static, data_root=data, media_root=media)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=IP, headers=CSRF) as c:
        yield c
