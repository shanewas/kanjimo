"""Admin API: invites and accounts. Admins are made with `python -m jstudy.cli admin <email>`."""
import logging

from fastapi import APIRouter, Body, Depends, Request

from .auth import ApiError, User, normalize_email, require_user

log = logging.getLogger("jstudy.admin")
router = APIRouter(prefix="/api/admin")


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise ApiError(403, "forbidden")
    return user


def invite_mail(origin: str) -> str:
    return (
        f"You have been invited to Kanjimo.\n\n"
        f"Sign in with this address at {origin}/app/#/account\n"
        "If you did not expect this, ignore this mail.\n"
    )


def _iso(value):
    return value.isoformat() if value else None


@router.get("/users")
def list_users(request: Request, admin: User = Depends(require_admin)):
    with request.app.state.pool.connection() as conn:
        users = conn.execute(
            "SELECT u.id, u.email, u.is_admin, u.created_at, u.disabled_at,"
            " (SELECT max(last_seen_at) FROM sessions s WHERE s.user_id = u.id) AS last_seen_at"
            " FROM users u ORDER BY u.id"
        ).fetchall()
        invites = conn.execute(
            "SELECT i.email, i.created_at, u.email AS invited_by FROM invites i"
            " LEFT JOIN users u ON u.id = i.invited_by ORDER BY i.created_at"
        ).fetchall()
    return {
        "users": [
            {"id": u["id"], "email": u["email"], "admin": u["is_admin"], "created_at": _iso(u["created_at"]),
             "disabled_at": _iso(u["disabled_at"]), "last_seen_at": _iso(u["last_seen_at"])}
            for u in users
        ],
        "invites": [
            {"email": i["email"], "created_at": _iso(i["created_at"]), "invited_by": i["invited_by"]} for i in invites
        ],
    }


@router.post("/invites", status_code=201)
def create_invite(request: Request, admin: User = Depends(require_admin), body: dict = Body(...)):
    st = request.app.state
    email = normalize_email(body.get("email"))
    if email is None:
        raise ApiError(400, "invalid_email")
    with st.pool.connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (email,)).fetchone():
            raise ApiError(409, "already_member")
        created = conn.execute(
            "INSERT INTO invites (email, invited_by, created_at) VALUES (%s, %s, %s)"
            " ON CONFLICT (email) DO NOTHING RETURNING email",
            (email, admin.id, st.clock()),
        ).fetchone()
    if created is None:
        raise ApiError(409, "already_invited")
    mailed = True
    try:
        st.mailer.send(email, "You're invited to Kanjimo", invite_mail(st.settings.public_origin))
    except Exception as exc:  # the invite stands without the mail; the admin can tell the person directly
        log.error("invite mail failed: %s: %s", type(exc).__name__, exc)
        mailed = False
    log.info("invite created by u=%s", admin.id)
    return {"email": email, "mailed": mailed}


@router.delete("/invites", status_code=204)
def revoke_invite(request: Request, admin: User = Depends(require_admin), body: dict = Body(...)):
    email = normalize_email(body.get("email"))
    if email is None:
        raise ApiError(400, "invalid_email")
    with request.app.state.pool.connection() as conn:
        if conn.execute("DELETE FROM invites WHERE email = %s RETURNING email", (email,)).fetchone() is None:
            raise ApiError(404, "not_found")


def _other_user(conn, admin: User, user_id: int) -> None:
    if user_id == admin.id:
        raise ApiError(400, "self")
    if conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone() is None:
        raise ApiError(404, "not_found")


@router.patch("/users/{user_id}")
def update_user(request: Request, user_id: int, admin: User = Depends(require_admin), body: dict = Body(...)):
    disabled = body.get("disabled")
    if not isinstance(disabled, bool):
        raise ApiError(400, "bad_request")
    st = request.app.state
    with st.pool.connection() as conn:
        _other_user(conn, admin, user_id)
        conn.execute("UPDATE users SET disabled_at = %s WHERE id = %s", (st.clock() if disabled else None, user_id))
        if disabled:
            conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    log.info("user %s %s by u=%s", user_id, "disabled" if disabled else "enabled", admin.id)
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(request: Request, user_id: int, admin: User = Depends(require_admin), body: dict = Body(...)):
    if body.get("confirm") != "delete":
        raise ApiError(400, "confirm_required")
    with request.app.state.pool.connection() as conn:
        _other_user(conn, admin, user_id)
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    log.info("user %s deleted by u=%s", user_id, admin.id)
