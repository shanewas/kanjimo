"""Sign in with Google: OpenID Connect code flow with PKCE, server side. Off unless both GOOGLE_ settings are set."""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .auth import _open_session, client_ip, normalize_email, set_session_cookie

log = logging.getLogger("jstudy.google")
router = APIRouter()

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
FLOW_TTL = 600
# Google only vouches for addresses it hosts: Gmail, or a Workspace domain (the hd claim). Any other
# address on a Google account was verified once by Google and may have changed hands since.
GMAIL = ("@gmail.com", "@googlemail.com")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _cookie_name(settings) -> str:
    return "jstudy-g" if settings.dev else "__Host-jstudy-g"


def _sign(settings, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(settings.session_pepper.encode(), b"google:" + body.encode(), hashlib.sha256).digest()
    return body + "." + _b64(mac)


def _unsign(settings, value: str | None) -> dict | None:
    if not value or len(value) > 1024 or "." not in value:
        return None
    body, _, mac = value.partition(".")
    good = hmac.new(settings.session_pepper.encode(), b"google:" + body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_unb64(mac), good):
            return None
        return json.loads(_unb64(body))
    except ValueError:
        return None


class GoogleClient:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id, self.client_secret = client_id, client_secret

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> dict:
        """Returns the id_token claims. The token comes straight from Google over TLS, which OpenID Connect
        Core 3.1.3.7 accepts in place of checking its signature."""
        data = urllib.parse.urlencode({
            "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=data, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            token = json.load(res)["id_token"]
        return json.loads(_unb64(token.split(".")[1]))


def _back(error: str | None = None) -> RedirectResponse:
    return RedirectResponse("/app/#/account" + (f"?login={error}" if error else ""), status_code=303)


def _redirect_uri(settings) -> str:
    return settings.public_origin + "/api/auth/google/callback"


@router.get("/api/auth/google/start")
def start(request: Request):
    st = request.app.state
    google = getattr(st, "google", None)
    if google is None:
        return _back("google_unavailable")
    flow = {"state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24),
            "verifier": secrets.token_urlsafe(48), "exp": int(st.clock().timestamp()) + FLOW_TTL}
    query = urllib.parse.urlencode({
        "client_id": google.client_id, "redirect_uri": _redirect_uri(st.settings), "response_type": "code",
        "scope": "openid email", "state": flow["state"], "nonce": flow["nonce"], "prompt": "select_account",
        "code_challenge": _b64(hashlib.sha256(flow["verifier"].encode()).digest()), "code_challenge_method": "S256",
    })
    response = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=303)
    response.set_cookie(_cookie_name(st.settings), _sign(st.settings, flow), max_age=FLOW_TTL, path="/",
                        secure=not st.settings.dev, httponly=True, samesite="lax")
    return response


@router.get("/api/auth/google/callback")
def callback(request: Request):
    st = request.app.state
    google = getattr(st, "google", None)
    if google is None:
        return _back("google_unavailable")
    now = st.clock()
    flow = _unsign(st.settings, request.cookies.get(_cookie_name(st.settings)))
    params = request.query_params
    if (flow is None or flow.get("exp", 0) < now.timestamp()
            or not hmac.compare_digest(str(params.get("state", "")), flow["state"])):
        return _back("google_failed")
    if params.get("error") or not params.get("code"):
        return _back("google_cancelled")
    try:
        claims = google.exchange(params["code"], flow["verifier"], _redirect_uri(st.settings))
    except (urllib.error.URLError, KeyError, ValueError, IndexError, TimeoutError) as exc:
        log.error("google token exchange failed: %s: %s", type(exc).__name__, exc)
        return _back("google_failed")
    email = normalize_email(claims.get("email"))
    if (claims.get("iss") not in ISSUERS or claims.get("aud") != google.client_id
            or not isinstance(claims.get("exp"), int) or claims["exp"] < now.timestamp()
            or not hmac.compare_digest(str(claims.get("nonce", "")), flow["nonce"])):
        log.warning("google id_token rejected: iss=%s aud_ok=%s", claims.get("iss"), claims.get("aud") == google.client_id)
        return _back("google_failed")
    if email is None or claims.get("email_verified") is not True or not (email.endswith(GMAIL) or claims.get("hd")):
        return _back("google_email")
    with st.pool.connection() as conn:
        opened = _open_session(conn, request, email, client_ip(request), now)
    if opened is None:
        return _back("not_invited")
    response = _back()
    token = opened[1]
    set_session_cookie(response, st.settings, token)
    response.delete_cookie(_cookie_name(st.settings), path="/", secure=not st.settings.dev, httponly=True, samesite="lax")
    return response
