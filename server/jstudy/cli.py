"""Operator commands, run over SSH: python -m jstudy.cli [--env /etc/jstudy/prod.env] <command>."""
import argparse
import sys

from . import db
from .config import Settings, load_env_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m jstudy.cli", description="jstudy operator commands")
    parser.add_argument("--env", metavar="FILE", help="KEY=VALUE file to load before reading settings")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply sql/*.sql files not yet recorded in schema_migrations")
    delete = commands.add_parser("delete-user", help="delete the account and its progress")
    delete.add_argument("email")
    invite = commands.add_parser("invite", help="let this address sign in (invite-only)")
    invite.add_argument("email")
    admin = commands.add_parser("admin", help="make this address an admin, creating the account if needed")
    admin.add_argument("email")
    return parser


def _user_id(conn, email: str) -> int:
    row = conn.execute("SELECT id FROM users WHERE lower(email) = lower(%s)", (email,)).fetchone()
    if row is None:
        raise SystemExit(f"no user with email {email}")
    return row["id"]


def run(args, pool, out=sys.stdout) -> int:
    with pool.connection() as conn:
        if args.command == "migrate":
            applied = db.migrate(conn)
            print("applied: " + (", ".join(applied) or "nothing"), file=out)
        elif args.command == "delete-user":
            user_id = _user_id(conn, args.email)
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
            print(f"deleted user {user_id}", file=out)
        elif args.command == "invite":
            conn.execute("INSERT INTO invites (email) VALUES (lower(%s)) ON CONFLICT DO NOTHING", (args.email,))
            print(f"invited {args.email.lower()}", file=out)
        elif args.command == "admin":
            row = conn.execute(
                "INSERT INTO users (email, is_admin) VALUES (lower(%s), true)"
                " ON CONFLICT (lower(email)) DO UPDATE SET is_admin = true RETURNING id",
                (args.email,),
            ).fetchone()
            conn.execute("DELETE FROM invites WHERE email = lower(%s)", (args.email,))
            print(f"user {row['id']} is admin", file=out)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.env:
        load_env_file(args.env)
    settings = Settings.from_env()
    pool = db.make_pool(settings.database_url)
    pool.open()
    try:
        return run(args, pool)
    finally:
        pool.close()


if __name__ == "__main__":
    sys.exit(main())
