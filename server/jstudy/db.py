"""Connection pool, numbered SQL migrations and the hourly sweep."""
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SQL_DIR = Path(__file__).parent / "sql"
SWEEP_SECONDS = 3600.0
log = logging.getLogger("jstudy.db")


def make_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(database_url, kwargs={"row_factory": dict_row}, min_size=1, max_size=4, open=False)


def migrate(conn) -> list[str]:
    """Applies sql/NNNN_*.sql in name order. Each file runs once, in one transaction with its ledger row."""
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations"
            " (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(SQL_DIR.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def sweep(conn, now: datetime) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at <= %s", (now,))
    conn.execute("DELETE FROM login_codes WHERE created_at < %s", (now - timedelta(days=1),))
    conn.execute("DELETE FROM verify_attempts WHERE created_at < %s", (now - timedelta(days=1),))


class SweepWorker(threading.Thread):
    """Background thread that runs the sweep every hour."""

    def __init__(self, state) -> None:
        super().__init__(name="jstudy-sweep", daemon=True)
        self.state = state
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                with self.state.pool.connection() as conn:
                    sweep(conn, self.state.clock())
            except Exception as exc:  # keep the loop alive through a DB blip; the next round retries
                log.error("sweep failed: %s: %s", type(exc).__name__, exc)
            self.stop.wait(SWEEP_SECONDS)
