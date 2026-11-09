"""Operator CLI for service accounts. See docs/runbooks/operations.md.

python -m app.admin list | rotate <name> | disable <name> | enable <name>
"""
import argparse
import json
import secrets

from .config import Settings
from .db import Database, hash_key


def rotate(db: Database, name: str) -> str:
    """Issue a new key for an external account. The old key stops working at once; the new one is shown once."""
    key = secrets.token_urlsafe(32)
    with db.connect() as conn:
        updated = conn.execute(
            "UPDATE service_accounts SET key_hash = ?, rotated_at = datetime('now') WHERE name = ? AND kind = 'external'",
            (hash_key(key), name)).rowcount
        if not updated:
            raise SystemExit(f"No external service account named {name}.")
        conn.execute("INSERT INTO audit_log(actor, action, target, decision, reason) VALUES ('operator-cli',"
                     " 'service:rotate', ?, 'allow', 'key rotated')", (name,))
    return key


def set_active(db: Database, name: str, active: bool) -> None:
    with db.connect() as conn:
        if not conn.execute("UPDATE service_accounts SET active = ? WHERE name = ?", (int(active), name)).rowcount:
            raise SystemExit(f"No service account named {name}.")
        conn.execute("INSERT INTO audit_log(actor, action, target, decision, reason) VALUES ('operator-cli',"
                     " 'service:set_active', ?, 'allow', ?)", (name, f"active={active}"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "rotate", "disable", "enable"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    settings = Settings()
    db = Database(settings.db_path)
    db.init(settings.demo_password)
    if args.command == "list":
        with db.connect() as conn:
            for r in conn.execute("SELECT name, kind, active, scopes, rotated_at FROM service_accounts"):
                print(r["name"], r["kind"], "active" if r["active"] else "DISABLED", json.loads(r["scopes"]), r["rotated_at"])
    elif not args.name:
        parser.error("this command needs a service account name")
    elif args.command == "rotate":
        print(rotate(db, args.name))
    else:
        set_active(db, args.name, args.command == "enable")


if __name__ == "__main__":
    main()
