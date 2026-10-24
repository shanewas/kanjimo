# jstudy server

FastAPI + PostgreSQL 16 backend for the study app: emailed six-digit login codes, cookie sessions,
Google sign-in, progress sync with `If-Match` revisions, and the two `auth_request` endpoints nginx calls
before serving gated content. There is no billing: every level is open to any signed-in user.

Runtime dependencies (pinned in `requirements.txt`): `fastapi`, `uvicorn`, `psycopg[binary,pool]`.
Python 3.11 or newer.

## Setup

```
py -3.11 -m venv C:\Users\<you>\japanese_study_build\venv
C:\Users\<you>\japanese_study_build\venv\Scripts\python -m pip install -r server\requirements-dev.txt
```

`requirements-dev.txt` adds `pytest`, `httpx` (TestClient) and `pgserver` (embedded PostgreSQL binaries,
test only, never deployed).

## Tests

```
C:\Users\<you>\japanese_study_build\venv\Scripts\python -m pytest server\tests -q
```

The session fixture starts a throwaway PostgreSQL through `pgserver` under
`<repo parent>\<repo name>_build\pg\pg-<random>` (override with `JSTUDY_TEST_PGDIR`), bound to 127.0.0.1,
creates `jstudy_test`, applies `jstudy/sql/*.sql`, truncates every table between tests, and stops and
deletes the server at the end. To run against an existing PostgreSQL instead, set
`JSTUDY_TEST_DATABASE_URL`; the suite refuses any database whose name does not end in `_test`.

Mail and the clock are fakes on `app.state` (`ListMailer`, `FakeClock` in `tests/conftest.py`). No test
opens a network connection.

On Linux `pgserver` listens on a Unix socket, which the fixture's 127.0.0.1 check rejects; start a
`pgserver` yourself and pass its `jstudy_test` URI in `JSTUDY_TEST_DATABASE_URL`.

## Dev server

```
cd server
set JSTUDY_DEV=1
set PUBLIC_ORIGIN=http://127.0.0.1:8765
set DATABASE_URL=postgresql://postgres@127.0.0.1:5432/jstudy_dev
set SESSION_PEPPER=<openssl rand -base64 32>
set JSTUDY_STATIC_ROOT=..\app
set JSTUDY_DATA_ROOT=..\data
..\..\japanese_study_build\venv\Scripts\python -m jstudy.cli migrate
..\..\japanese_study_build\venv\Scripts\uvicorn jstudy.main:app --host 127.0.0.1 --port 8765
```

Dev mode serves the frontend at `/app/` and the content tree at `/data/` (and `/media/` when
`JSTUDY_MEDIA_ROOT` is set) with the same login and daily-budget checks nginx applies in production, prints login
codes to the console instead of sending mail, names the cookie `jstudy` without `Secure`, and refuses to
start unless `PUBLIC_ORIGIN` is a loopback origin. A throwaway database for the dev loop:

```
python -c "import pgserver; s = pgserver.get_server(r'C:\Users\<you>\japanese_study_build\pg\dev'); print(s.get_uri())"
```

(then `CREATE DATABASE jstudy_dev` and use that URI with the database name swapped).

## Environment variables

Required: `DATABASE_URL`, `PUBLIC_ORIGIN`, `SESSION_PEPPER` (16+ characters). Required outside dev mode:
`MAIL_FROM`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` (`SMTP_PORT` defaults to 587, STARTTLS).
Optional: `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, `JSTUDY_DEV`, `JSTUDY_STATIC_ROOT`,
`JSTUDY_DATA_ROOT`, `JSTUDY_MEDIA_ROOT`, `PORT` (read by the systemd unit only). Leftover `STRIPE_*`
lines in an env file are ignored.

Levels 1 to `MAX_LEVEL` (`jstudy/config.py`) need a login and count toward a per-user daily budget of
`DAILY_HITS` level files; the level regex in `deploy/nginx-jstudy-*.conf` mirrors `gate_for`.

## Operator commands

```
python -m jstudy.cli [--env /etc/jstudy/prod.env] migrate
python -m jstudy.cli delete-user <email>
```

The `entitlements`, `stripe_webhook_inbox`, `payments` and `settings` tables from the billing era stay in
the schema unused; dropping them is a separate, deliberate migration.

`deploy/` holds the systemd unit, the nginx vhosts and header snippet, and the cloudflared ingress
snippet with `<zone>` placeholders. `deploy/kanjimo-deploy` builds a release from a commit on `main` and swaps
it in; CI runs it over SSH after the tests pass.
