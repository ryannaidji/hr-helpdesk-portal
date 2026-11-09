"""SQLite schema, connection helper and synthetic seed data."""
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from .config import DATA_DIR
from .leave import required_approver, working_days

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('employee','manager','hr')),
  manager_id TEXT REFERENCES employees(id), department TEXT NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leave_balances (
  employee_id TEXT NOT NULL REFERENCES employees(id), leave_type TEXT NOT NULL, days REAL NOT NULL,
  PRIMARY KEY (employee_id, leave_type));
CREATE TABLE IF NOT EXISTS leave_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL REFERENCES employees(id),
  leave_type TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, days REAL NOT NULL,
  reason TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected')),
  required_approver TEXT NOT NULL CHECK (required_approver IN ('manager','hr')),
  created_by TEXT NOT NULL, decided_by TEXT, decided_at TEXT, decision_note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')),
  actor TEXT NOT NULL, via_service TEXT, action TEXT NOT NULL, target TEXT,
  decision TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', trace_id TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TABLE IF NOT EXISTS escalations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL REFERENCES employees(id),
  score INTEGER NOT NULL, level TEXT NOT NULL, reasons TEXT NOT NULL, message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')), resolved_by TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS service_accounts (
  name TEXT PRIMARY KEY, key_hash TEXT, scopes TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('internal','external')),
  active INTEGER NOT NULL DEFAULT 1, rotated_at TEXT);
"""

# Scopes are the ceiling for each non-human identity. Internal agents carry no key: they exist only
# inside the server process and always act on behalf of an authenticated user.
SERVICE_ACCOUNTS = {
    "svc-policy-agent": ("internal", ["policy:read"]),
    "svc-hr-action-agent": ("internal", ["leave:read:self", "leave:read:reports", "leave:request:self"]),
    "svc-escalation-agent": ("internal", ["escalation:create"]),
    "svc-leave-report": ("external", ["reports:aggregate"]),
}


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt = stored.split("$", 1)[0]
    return secrets.compare_digest(hash_password(password, salt), stored)


def hash_key(key: str) -> str:
    # Keys are 256-bit random values, so a fast hash is appropriate (unlike passwords).
    return hashlib.sha256(key.encode()).hexdigest()


class Database:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self, demo_password: str) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            for name, (kind, scopes) in SERVICE_ACCOUNTS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO service_accounts(name, scopes, kind) VALUES (?,?,?)",
                    (name, json.dumps(scopes), kind),
                )
            if conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]:
                return
            seed = json.loads((DATA_DIR / "seed.json").read_text(encoding="utf-8"))
            pw = hash_password(demo_password)
            conn.execute("PRAGMA defer_foreign_keys = ON")
            for e in seed["employees"]:
                conn.execute(
                    "INSERT INTO employees VALUES (?,?,?,?,?,?)",
                    (e["id"], e["name"], e["role"], e["manager_id"], e["department"], pw),
                )
                for leave_type, days in e["balances"].items():
                    conn.execute("INSERT INTO leave_balances VALUES (?,?,?)", (e["id"], leave_type, days))
            for r in seed["leave_requests"]:
                days = working_days(r["start_date"], r["end_date"])
                conn.execute(
                    "INSERT INTO leave_requests(employee_id, leave_type, start_date, end_date, days, reason,"
                    " required_approver, created_by) VALUES (?,?,?,?,?,?,?,?)",
                    (r["employee_id"], r["leave_type"], r["start_date"], r["end_date"], days, r["reason"],
                     required_approver(r["leave_type"], days), r["employee_id"]),
                )
