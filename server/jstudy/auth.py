"""Email-code login, sessions, the nginx auth_request endpoints and the gate table."""
import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request, Response
from psycopg import sql

from .config import MAX_LEVEL

log = logging.getLogger("jstudy.auth")
router = APIRouter()

CODE_TTL = timedelta(minutes=10)
CODE_ATTEMPTS = 5
CODES_PER_EMAIL_HOUR = 5
CODES_PER_IP_HOUR = 20
VERIFIES_PER_IP_HOUR = 30
SESSION_TTL = timedelta(days=30)
SESSION_MAX = timedelta(days=365)
SESSION_BUMP = timedelta(minutes=10)
DAILY_HITS = 300
HOUR = timedelta(hours=1)
EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
CODE_RE = re.compile(r"\d{8}")  # 5 codes/h x 5 tries: a year of guessing finds one in ~0.2%
PUBLIC_DATA = frozenset({"/data/index.json", "/data/LICENSE-DATA.txt", "/data/ATTRIBUTION.json"})
LEVEL_RE = re.compile(r"/data/(cards|items|levels|own)/level-(\d{2})\.json")
AUDIO_RE = re.compile(r"/media/audio/[a-f0-9]{16,64}\.(mp3|webm)")
IMAGE_RE = re.compile(r"/data/images/[a-z0-9-]{1,40}\.svg")  # KanjiVG parts without a Unicode glyph


class ApiError(Exception):
    def __init__(self, status: int, error: str, headers: dict | None = None, **extra):
        super().__init__(error)
        self.status, self.error, self.headers, self.extra = status, error, headers, extra


@dataclass(frozen=True)
class User:
    id: int
    email: str
    is_admin: bool = False

    def json(self) -> dict:
        return {"id": self.id, "email": self.email, "admin": self.is_admin}


def normalize_email(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    email = raw.strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        return None
    return email


def code_hash(pepper: str, email: str, code: str) -> bytes:
    return hmac.new(pepper.encode(), f"{email}:{code}".encode(), hashlib.sha256).digest()


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def client_ip(request: Request):
    try:
        return ipaddress.ip_address(request.client.host) if request.client else None
    except ValueError:
        return None


def gate_for(path: str) -> str | None:
    """Mirror of the nginx location table: 'public', 'login', 'budget' (login plus the daily file budget),
    or None for everything else (404)."""
    if path in PUBLIC_DATA:
        return "public"
    if path == "/data/search-index.json" or AUDIO_RE.fullmatch(path) or IMAGE_RE.fullmatch(path):
        return "login"
    match = LEVEL_RE.fullmatch(path)
    if match and 1 <= int(match.group(2)) <= MAX_LEVEL:
        return "budget"
    return None


def load_user(request: Request) -> User | None:
    st = request.app.state
    token = request.cookies.get(st.settings.cookie_name)
    if not token or len(token) > 128:
        return None
    now = st.clock()
    th = token_hash(token)
    with st.pool.connection() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.created_at, s.last_seen_at, s.expires_at, u.email, u.is_admin"
            " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = %s AND u.disabled_at IS NULL",
            (th,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now:
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (th,))
            return None
        if now - row["last_seen_at"] >= SESSION_BUMP:
            conn.execute(
                "UPDATE sessions SET last_seen_at = %s, expires_at = %s WHERE token_hash = %s",
                (now, min(now + SESSION_TTL, row["created_at"] + SESSION_MAX), th),
            )
            request.state.session_bumped = True
    return User(row["user_id"], row["email"], row["is_admin"])


def require_user(request: Request, response: Response) -> User:
    user = load_user(request)
    if user is None:
        raise ApiError(401, "login_required")
    if getattr(request.state, "session_bumped", False):
        # The cookie's Max-Age was fixed at login; without this it expires while the session row lives on.
        settings = request.app.state.settings
        set_session_cookie(response, settings, request.cookies[settings.cookie_name])
    return user


def set_session_cookie(response: Response, settings, token: str) -> None:
    response.set_cookie(
        settings.cookie_name, token, max_age=int(SESSION_TTL.total_seconds()), path="/",
        secure=not settings.dev, httponly=True, samesite="lax",
    )


def clear_session_cookie(response: Response, settings) -> None:
    if "set-cookie" in response.headers:  # a refresh from require_user must not sit beside the delete
        del response.headers["set-cookie"]
    response.delete_cookie(settings.cookie_name, path="/", secure=not settings.dev, httponly=True, samesite="lax")


def _advisory_lock(conn, key: str) -> None:
    """Serialises callers sharing `key` until the current transaction ends."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def _limit(conn, column: str, value, now: datetime, cap: int) -> None:
    _advisory_lock(conn, f"login_codes:{column}:{value}")
    row = conn.execute(
        sql.SQL("SELECT count(*) AS n, min(created_at) AS oldest FROM login_codes WHERE {} = %s AND created_at > %s")
        .format(sql.Identifier(column)),
        (value, now - HOUR),
    ).fetchone()
    if row["n"] >= cap:
        wait = max(1, int((row["oldest"] + HOUR - now).total_seconds()) + 1)
        raise ApiError(429, "too_many_requests", headers={"Retry-After": str(wait)}, retry_after=wait)


def admitted(conn, email: str) -> bool:
    """Invite-only: an active account or a pending invite may sign in."""
    return conn.execute(
        "SELECT 1 FROM users WHERE lower(email) = %s AND disabled_at IS NULL"
        " UNION ALL SELECT 1 FROM invites WHERE email = %s",
        (email, email),
    ).fetchone() is not None


def code_mail(code: str, origin: str) -> str:
    return (
        f"Your sign-in code is {code}\n\n"
        f"It expires in 10 minutes. Enter it at {origin}/app/#/account\n"
        "If you did not request it, ignore this mail.\n"
    )


@router.post("/api/auth/code", status_code=202)
def request_code(request: Request, tasks: BackgroundTasks, body: dict = Body(...)):
    """Answers 202 alike for invited, uninvited and over-limit addresses, and mails after the response,
    so neither the status nor the timing tells who is invited."""
    st = request.app.state
    now = st.clock()
    email = normalize_email(body.get("email"))
    if email is None:
        raise ApiError(400, "invalid_email")
    ip = client_ip(request)
    code = f"{secrets.randbelow(10**8):08d}"
    with st.pool.connection() as conn:
        if ip is not None:
            _limit(conn, "ip", ip, now, CODES_PER_IP_HOUR)
        if not admitted(conn, email):
            return {"ok": True}
        try:
            _limit(conn, "email", email, now, CODES_PER_EMAIL_HOUR)
        except ApiError:
            log.warning("login code cap reached for an invited address")
            return {"ok": True}
        conn.execute(
            "UPDATE login_codes SET used_at = %s WHERE email = %s AND used_at IS NULL", (now, email),
        )
        row = conn.execute(
            "INSERT INTO login_codes (email, code_hash, ip, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)"
            " RETURNING id",
            (email, code_hash(st.settings.session_pepper, email, code), ip, now, now + CODE_TTL),
        ).fetchone()
    tasks.add_task(_mail_code, st, email, code, now, row["id"])
    return {"ok": True}


def _mail_code(st, email: str, code: str, now: datetime, code_id: int) -> None:
    try:
        st.mailer.send(email, "Your sign-in code", code_mail(code, st.settings.public_origin))
    except Exception as exc:  # provider-agnostic boundary: whatever failed, the code must not stay usable
        log.error("login code mail failed: %s: %s", type(exc).__name__, exc)
        with st.pool.connection() as conn:
            conn.execute("UPDATE login_codes SET used_at = %s WHERE id = %s AND used_at IS NULL", (now, code_id))


@router.post("/api/auth/verify")
def verify_code(request: Request, response: Response, body: dict = Body(...)):
    st = request.app.state
    now = st.clock()
    email = normalize_email(body.get("email"))
    code = body.get("code")
    if email is None or not isinstance(code, str) or not CODE_RE.fullmatch(code):
        raise ApiError(400, "invalid_code")
    ip = client_ip(request)
    opened = matched = None
    with st.pool.connection() as conn:
        if ip is not None:
            _advisory_lock(conn, f"verify_attempts:ip:{ip}")
            # Counted by the verifying IP: a guesser elsewhere would not show up in login_codes.ip.
            tries = conn.execute(
                "SELECT count(*) AS n FROM verify_attempts WHERE ip = %s AND created_at > %s", (ip, now - HOUR),
            ).fetchone()["n"]
            if tries >= VERIFIES_PER_IP_HOUR:
                raise ApiError(429, "too_many_requests", headers={"Retry-After": "3600"}, retry_after=3600)
            conn.execute("INSERT INTO verify_attempts (ip, created_at) VALUES (%s, %s)", (ip, now))
        row = conn.execute(
            "SELECT id, code_hash, attempts FROM login_codes"
            " WHERE email = %s AND used_at IS NULL AND expires_at > %s"
            " ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE",
            (email, now),
        ).fetchone()
        # The attempt counter must survive a wrong guess, so no exception is raised inside this transaction.
        if row is not None and row["attempts"] < CODE_ATTEMPTS:
            conn.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE id = %s", (row["id"],))
            if hmac.compare_digest(bytes(row["code_hash"]), code_hash(st.settings.session_pepper, email, code)):
                conn.execute("UPDATE login_codes SET used_at = %s WHERE id = %s", (now, row["id"]))
                matched = True
                opened = _open_session(conn, request, email, ip, now)
    if opened is None:
        # A right code for an address disabled or uninvited since the code was sent.
        raise ApiError(403, "not_invited") if matched else ApiError(400, "invalid_code")
    user, token = opened
    set_session_cookie(response, st.settings, token)
    return {"user": user.json()}


def _open_session(conn, request: Request, email: str, ip, now: datetime):
    """Returns (user, token), or None when the address is neither an active account nor invited.
    The first sign-in turns the invite into the account."""
    _advisory_lock(conn, f"open_session:{email}")
    # Read only after the lock: a concurrent first sign-in for this address has
    # committed by now, so its new account is picked up instead of rejected.
    row = conn.execute("SELECT id, is_admin, disabled_at FROM users WHERE lower(email) = %s", (email,)).fetchone()
    if row is None:
        if conn.execute("DELETE FROM invites WHERE email = %s RETURNING email", (email,)).fetchone() is None:
            return None
        row = conn.execute(
            "INSERT INTO users (email, created_at) VALUES (%s, %s) RETURNING id, is_admin, disabled_at", (email, now),
        ).fetchone()
    if row["disabled_at"] is not None:
        return None
    user_id = row["id"]
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, last_seen_at, expires_at, ip, user_agent)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (token_hash(token), user_id, now, now, now + SESSION_TTL, ip, request.headers.get("user-agent", "")[:512]),
    )
    return User(user_id, email, row["is_admin"]), token


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, user: User = Depends(require_user), body: dict | None = Body(None)):
    st = request.app.state
    with st.pool.connection() as conn:
        if body and body.get("all") is True:
            conn.execute("DELETE FROM sessions WHERE user_id = %s", (user.id,))
        else:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = %s",
                (token_hash(request.cookies[st.settings.cookie_name]),),
            )
    clear_session_cookie(response, st.settings)


@router.get("/api/me")
def me(user: User = Depends(require_user)):
    return {"user": user.json()}


@router.delete("/api/me", status_code=204)
def delete_me(request: Request, response: Response, user: User = Depends(require_user), body: dict = Body(...)):
    st = request.app.state
    if body.get("confirm") != "delete":
        raise ApiError(400, "confirm_required")
    with st.pool.connection() as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (user.id,))
    clear_session_cookie(response, st.settings)


@router.get("/api/auth/check")
def check(request: Request):
    user = load_user(request)
    if user is None:
        raise ApiError(401, "login_required")
    return Response(status_code=204, headers={"X-JStudy-User": str(user.id)})


@router.get("/api/auth/check-budget")
def check_budget(request: Request):
    user = load_user(request)
    if user is None:
        raise ApiError(401, "login_required")
    budget_hit(request, user)
    return Response(status_code=204, headers={"X-JStudy-User": str(user.id)})


def budget_hit(request: Request, user: User) -> None:
    """One level-file request: counts toward today's budget, which stops bulk downloads."""
    st = request.app.state
    now = st.clock()
    uri = request.headers.get("x-original-uri") or request.url.path
    with st.pool.connection() as conn:
        hits = conn.execute(
            "INSERT INTO data_hits (user_id, day, hits) VALUES (%s, %s, 1)"
            " ON CONFLICT (user_id, day) DO UPDATE SET hits = data_hits.hits + 1 RETURNING hits",
            (user.id, now.date()),
        ).fetchone()["hits"]
    if hits > DAILY_HITS:
        log.warning("gated denied u=%s reason=budget uri=%s hits=%s", user.id, uri, hits)
        raise ApiError(403, "daily_limit", headers={"X-Deny-Reason": "budget"})
