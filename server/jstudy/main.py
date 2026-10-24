"""App factory: host and CSRF middleware, routers, lifespan (pool, sweep thread), dev-mode static serving."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import psycopg_pool
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from . import admin, auth, google, progress
from .auth import ApiError, budget_hit, gate_for, load_user
from .config import Settings
from .db import SweepWorker, make_pool
from .mailer import ConsoleMailer, SmtpMailer

log = logging.getLogger("jstudy")

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "jstudy"
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEV_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com;"
        " font-src https://fonts.gstatic.com; img-src 'self' data:; media-src 'self'; connect-src 'self';"
        " base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}
STATUS_ERRORS = {404: "not_found", 405: "method_not_allowed"}


class CsrfMiddleware:
    """Rejects mutating requests without the app's custom header or from another site."""

    def __init__(self, app, origin: str) -> None:
        self.app = app
        self.origin = origin

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in MUTATING:
            headers = Headers(scope=scope)
            site = headers.get("sec-fetch-site")
            origin = headers.get("origin")
            if (
                headers.get(CSRF_HEADER) != CSRF_VALUE
                or (site is not None and site != "same-origin")
                or (origin is not None and origin != self.origin)
            ):
                await JSONResponse({"error": "csrf"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class DevHeadersMiddleware:
    """Dev only: the headers nginx adds in production, so the browser meets the same CSP locally."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in DEV_HEADERS.items():
                    headers[name] = value
                if scope["path"].startswith("/app/"):
                    headers["Cache-Control"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _api_error(request: Request, exc: ApiError):
    return JSONResponse({"error": exc.error, **exc.extra}, status_code=exc.status, headers=exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"error": "bad_request"}, status_code=400)


async def _http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        {"error": STATUS_ERRORS.get(exc.status_code, "error")}, status_code=exc.status_code, headers=exc.headers
    )


def create_app(settings: Settings | None = None, *, worker: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool.open()
        thread = SweepWorker(app.state) if worker else None
        if thread:
            thread.start()
        try:
            yield
        finally:
            if thread:
                thread.stop.set()
                thread.join(timeout=15)
            app.state.pool.close()

    app = FastAPI(title="jstudy", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.pool = make_pool(settings.database_url)
    app.state.clock = lambda: datetime.now(timezone.utc)
    app.state.mailer = (
        ConsoleMailer() if settings.dev
        else SmtpMailer(settings.smtp_host, settings.smtp_port, settings.smtp_user, settings.smtp_password,
                        settings.mail_from)
    )
    app.state.google = (
        google.GoogleClient(settings.google_client_id, settings.google_client_secret)
        if settings.google_client_id and settings.google_client_secret else None
    )
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_middleware(CsrfMiddleware, origin=settings.public_origin)
    if settings.dev:
        app.add_middleware(DevHeadersMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[settings.host])
    app.include_router(auth.router)
    app.include_router(google.router)
    app.include_router(progress.router)
    app.include_router(admin.router)

    @app.get("/api/health")
    def health(request: Request):
        try:
            with request.app.state.pool.connection() as conn:
                conn.execute("SELECT 1")
        except (psycopg.Error, psycopg_pool.PoolTimeout) as exc:
            log.error("health check: database unreachable: %s", exc)
            return JSONResponse({"ok": False, "db": False}, status_code=503)
        return {"ok": True, "db": True}

    if settings.dev:
        _mount_dev(app, settings)
    return app


def _mount_dev(app: FastAPI, settings: Settings) -> None:
    """Serves the frontend and the content directory with the same gate nginx applies in production."""

    def gated(prefix: str, root: Path):
        def serve(request: Request, path: str):
            url_path = request.url.path
            if any(bad in url_path for bad in ("..", "\0", "\\", ":")):
                raise ApiError(404, "not_found")
            tier = gate_for(url_path)
            if tier is None:
                raise ApiError(404, "not_found")
            if tier != "public":
                user = load_user(request)
                if user is None:
                    raise ApiError(401, "login_required")
                if tier == "budget":
                    budget_hit(request, user)
            file = (root / url_path[len(prefix):]).resolve()
            if not file.is_relative_to(root) or not file.is_file():
                raise ApiError(404, "not_found")
            cache = "public, max-age=3600" if tier == "public" else "private, max-age=86400"
            return FileResponse(file, headers={"Cache-Control": cache})
        return serve

    if settings.data_root:
        app.add_api_route("/data/{path:path}", gated("/data/", settings.data_root), methods=["GET"])
    if settings.media_root:
        app.add_api_route("/media/{path:path}", gated("/media/", settings.media_root), methods=["GET"])
    if settings.static_root:
        app.add_api_route("/", lambda: RedirectResponse("/app/"), methods=["GET"])
        app.mount("/app", StaticFiles(directory=settings.static_root, html=True), name="app")


def __getattr__(name):
    # `uvicorn jstudy.main:app` builds the app from the environment on first access, so importing the
    # module (tests, CLI) needs no settings.
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
