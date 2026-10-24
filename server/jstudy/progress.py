"""Progress mirror per user with optimistic revisions. The server checks shape and size only."""
import json

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb

from .auth import ApiError, User, require_user

router = APIRouter()

MAX_BYTES = 1_048_576
MAX_ITEMS = 20_000
MAX_DAYS = 4_000
MAX_KEY = 64
VERSIONS = (3, 4)


def validate_store(store) -> int:
    """Returns the serialised size. 400 for a wrong shape, 413 above the size cap."""
    if not isinstance(store, dict) or store.get("version") not in VERSIONS:
        raise ApiError(400, "bad_store")
    for key, cap in (("items", MAX_ITEMS), ("days", MAX_DAYS)):
        value = store.get(key)
        if not isinstance(value, dict) or len(value) > cap or any(len(k) > MAX_KEY for k in value):
            raise ApiError(400, "bad_store")
    size = len(json.dumps(store, separators=(",", ":"), ensure_ascii=False).encode())
    if size > MAX_BYTES:
        raise ApiError(413, "too_large")
    return size


def parse_if_match(value: str | None) -> int:
    digits = (value or "").strip().strip('"')
    if not digits.isdigit():
        raise ApiError(428, "if_match_required")
    return int(digits)


@router.get("/api/progress")
def get_progress(request: Request, user: User = Depends(require_user)):
    with request.app.state.pool.connection() as conn:
        row = conn.execute("SELECT rev, store, updated_at FROM progress WHERE user_id = %s", (user.id,)).fetchone()
    if row is None:
        return Response(status_code=204)
    return {"rev": row["rev"], "store": row["store"], "updated_at": row["updated_at"].isoformat()}


@router.put("/api/progress")
def put_progress(request: Request, user: User = Depends(require_user), body: dict = Body(...)):
    st = request.app.state
    expected = parse_if_match(request.headers.get("if-match"))
    store = body.get("store")
    size = validate_store(store)
    now = st.clock()
    with st.pool.connection() as conn:
        if expected == 0:
            row = conn.execute(
                "INSERT INTO progress (user_id, rev, store, bytes, updated_at) VALUES (%s, 1, %s, %s, %s)"
                " ON CONFLICT (user_id) DO NOTHING RETURNING rev, updated_at",
                (user.id, Jsonb(store), size, now),
            ).fetchone()
        else:
            # Plain UPDATE ... WHERE rev = expected: under READ COMMITTED the loser of a race re-reads the row
            # after the winner commits, sees the new rev and matches nothing.
            row = conn.execute(
                "UPDATE progress SET rev = rev + 1, store = %s, bytes = %s, updated_at = %s"
                " WHERE user_id = %s AND rev = %s RETURNING rev, updated_at",
                (Jsonb(store), size, now, user.id, expected),
            ).fetchone()
        if row is None:
            current = conn.execute("SELECT rev, store FROM progress WHERE user_id = %s", (user.id,)).fetchone()
            return JSONResponse(
                {"rev": current["rev"] if current else 0, "store": current["store"] if current else None},
                status_code=409,
            )
    return {"rev": row["rev"], "updated_at": row["updated_at"].isoformat()}
