"""HR operations. Every path here passes through a guard that authorizes and writes the audit row."""
import json
from dataclasses import dataclass
from datetime import date

from .authz import Actor, Decision, decide_on_employee, decide_scoped
from .db import Database
from .leave import LEAVE_TYPES, MAX_REQUEST_DAYS, required_approver, working_days


class Denied(Exception):
    """Same public message whether the target is forbidden or does not exist (no enumeration)."""

    PUBLIC = "Not authorized, or no such record."


class InvalidRequest(ValueError):
    pass


def _via(actor: Actor) -> str | None:
    return actor.via.name if actor.via else None


@dataclass
class HRService:
    db: Database
    # False only for the evaluation's negative control, which proves the leak detector can fire.
    # Deliberately not reachable from configuration or the environment.
    enforce: bool = True

    def audit(self, actor_id: str, via: str | None, action: str, target: str | None, decision: str,
              reason: str = "", trace_id: str | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO audit_log(actor, via_service, action, target, decision, reason, trace_id)"
                " VALUES (?,?,?,?,?,?,?)",
                (actor_id, via, action, target, decision, reason, trace_id),
            )

    def _deny(self, actor: Actor, action: str, target: str | None, reason: str, trace_id: str | None) -> None:
        self.audit(actor.employee_id, _via(actor), action, target, "deny", reason, trace_id)
        raise Denied(Denied.PUBLIC)

    def _record(self, actor: Actor, action: str, target: str | None, decision: Decision,
                trace_id: str | None) -> None:
        if decision.allowed:
            self.audit(actor.employee_id, _via(actor), action, target, "allow", decision.reason, trace_id)
        elif self.enforce:
            self._deny(actor, action, target, decision.reason, trace_id)
        else:
            self.audit(actor.employee_id, _via(actor), action, target, "allow_unenforced", decision.reason, trace_id)

    def _guard_employee(self, actor: Actor, action: str, target_id: str, trace_id: str | None) -> None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT manager_id FROM employees WHERE id = ?", (target_id,)).fetchone()
        if row is None:
            self._deny(actor, action, target_id, "unknown target", trace_id)
        self._record(actor, action, target_id, decide_on_employee(actor, action, target_id, row["manager_id"]), trace_id)

    def guard_scope(self, actor: Actor, scope: str, trace_id: str | None = None) -> None:
        self._record(actor, scope, None, decide_scoped(actor, scope), trace_id)

    def profile(self, employee_id: str) -> dict | None:
        """Identity of the logged-in user. Internal: callers pass only the authenticated id."""
        with self.db.connect() as conn:
            row = conn.execute("SELECT id, name, role, manager_id, department FROM employees WHERE id = ?",
                               (employee_id,)).fetchone()
        return dict(row) if row else None

    def get_balance(self, actor: Actor, employee_id: str, trace_id: str | None = None) -> dict:
        self._guard_employee(actor, "leave:read", employee_id, trace_id)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT leave_type, days FROM leave_balances WHERE employee_id = ?",
                                (employee_id,)).fetchall()
            name = conn.execute("SELECT name FROM employees WHERE id = ?", (employee_id,)).fetchone()["name"]
        return {"employee_id": employee_id, "name": name, "balances": {r["leave_type"]: r["days"] for r in rows}}

    def _present(self, actor: Actor, row: dict) -> dict:
        """Data minimisation: a manager never sees the reason on a sensitive (HR-routed) request."""
        visible = (actor.employee_id == row["employee_id"] or row["required_approver"] != "hr"
                   or "leave:read:all" in actor.effective_scopes)
        return row if visible or not self.enforce else {**row, "reason": None}

    def list_requests(self, actor: Actor, employee_id: str, trace_id: str | None = None) -> list[dict]:
        self._guard_employee(actor, "leave:read", employee_id, trace_id)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM leave_requests WHERE employee_id = ? ORDER BY start_date DESC",
                                (employee_id,)).fetchall()
        return [self._present(actor, dict(r)) for r in rows]

    def create_request(self, actor: Actor, employee_id: str, leave_type: str, start_date: str, end_date: str,
                       reason: str = "", trace_id: str | None = None, today: date | None = None) -> dict:
        self._guard_employee(actor, "leave:request", employee_id, trace_id)
        if leave_type not in LEAVE_TYPES:
            raise InvalidRequest(f"Unknown leave type. Choose one of: {', '.join(LEAVE_TYPES)}.")
        try:
            days = working_days(start_date, end_date)
        except ValueError as exc:
            raise InvalidRequest("Dates must be valid YYYY-MM-DD and end on or after the start.") from exc
        if date.fromisoformat(start_date) < (today or date.today()):
            raise InvalidRequest("Leave cannot start in the past.")
        if days == 0 or days > MAX_REQUEST_DAYS:
            raise InvalidRequest(f"A request must cover 1 to {MAX_REQUEST_DAYS} working days.")
        with self.db.connect() as conn:
            overlap = conn.execute(
                "SELECT 1 FROM leave_requests WHERE employee_id = ? AND status != 'rejected'"
                " AND start_date <= ? AND end_date >= ?", (employee_id, end_date, start_date)).fetchone()
            if overlap:
                raise InvalidRequest("This request overlaps an existing leave request.")
            if leave_type != "unpaid":
                balance = conn.execute("SELECT days FROM leave_balances WHERE employee_id = ? AND leave_type = ?",
                                       (employee_id, leave_type)).fetchone()
                pending = conn.execute(
                    "SELECT COALESCE(SUM(days),0) FROM leave_requests"
                    " WHERE employee_id = ? AND leave_type = ? AND status = 'pending'",
                    (employee_id, leave_type)).fetchone()[0]
                if balance is None or balance["days"] - pending < days:
                    raise InvalidRequest("Insufficient balance for this request.")
            cur = conn.execute(
                "INSERT INTO leave_requests(employee_id, leave_type, start_date, end_date, days, reason,"
                " required_approver, created_by) VALUES (?,?,?,?,?,?,?,?)",
                (employee_id, leave_type, start_date, end_date, days, reason,
                 required_approver(leave_type, days), _via(actor) or actor.employee_id))
            return dict(conn.execute("SELECT * FROM leave_requests WHERE id = ?", (cur.lastrowid,)).fetchone())

    def pending_approvals(self, actor: Actor, trace_id: str | None = None) -> list[dict]:
        """Requests this actor may decide. Managers do not see reports' HR-routed requests here."""
        scopes = actor.effective_scopes
        if "leave:decide:all" in scopes:
            where, args = "r.employee_id != ?", (actor.employee_id,)
        elif "leave:decide:reports" in scopes:
            where, args = "e.manager_id = ? AND r.required_approver = 'manager'", (actor.employee_id,)
        else:
            self._deny(actor, "leave:approvals", None, "no decide scope", trace_id)
        self.audit(actor.employee_id, _via(actor), "leave:approvals", None, "allow", "list queue", trace_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT r.*, e.name AS employee_name FROM leave_requests r JOIN employees e ON e.id = r.employee_id"
                f" WHERE r.status = 'pending' AND {where} ORDER BY r.created_at", args).fetchall()
        return [dict(r) for r in rows]

    def decide_request(self, actor: Actor, request_id: int, decision: str, note: str = "",
                       trace_id: str | None = None) -> dict:
        """Human approval step. No agent account holds a decide scope, so only a person can reach it."""
        if decision not in ("approved", "rejected"):
            raise InvalidRequest("Decision must be approved or rejected.")
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (request_id,)).fetchone()
        target = f"request:{request_id}"
        if row is None:
            self._deny(actor, "leave:decide", target, "unknown request", trace_id)
        self._guard_employee(actor, "leave:decide", row["employee_id"], trace_id)
        if self.enforce and row["required_approver"] == "hr" and "leave:decide:all" not in actor.effective_scopes:
            self._deny(actor, "leave:decide", target, "requires HR approval", trace_id)
        with self.db.connect() as conn:
            # The status guard in UPDATE makes double-approval (and double deduction) impossible.
            updated = conn.execute(
                "UPDATE leave_requests SET status = ?, decided_by = ?, decided_at = datetime('now'), decision_note = ?"
                " WHERE id = ? AND status = 'pending'", (decision, actor.employee_id, note, request_id)).rowcount
            if not updated:
                raise InvalidRequest("This request has already been decided.")
            if decision == "approved" and row["leave_type"] != "unpaid":
                conn.execute("UPDATE leave_balances SET days = days - ? WHERE employee_id = ? AND leave_type = ?",
                             (row["days"], row["employee_id"], row["leave_type"]))
            return dict(conn.execute("SELECT * FROM leave_requests WHERE id = ?", (request_id,)).fetchone())

    def audit_entries(self, actor: Actor, limit: int = 200, trace_id: str | None = None) -> list[dict]:
        self.guard_scope(actor, "audit:read", trace_id)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def list_escalations(self, actor: Actor, trace_id: str | None = None) -> list[dict]:
        self.guard_scope(actor, "escalation:read", trace_id)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM escalations ORDER BY status, score DESC, id DESC").fetchall()
        return [{**dict(r), "reasons": json.loads(r["reasons"])} for r in rows]

    def resolve_escalation(self, actor: Actor, ticket_id: int, trace_id: str | None = None) -> dict:
        self.guard_scope(actor, "escalation:read", trace_id)
        with self.db.connect() as conn:
            updated = conn.execute("UPDATE escalations SET status = 'resolved', resolved_by = ?, resolved_at = datetime('now')"
                                   " WHERE id = ? AND status = 'open'", (actor.employee_id, ticket_id)).rowcount
            if not updated:
                raise InvalidRequest("No open escalation with that id.")
        self.audit(actor.employee_id, _via(actor), "escalation:resolve", f"escalation:{ticket_id}", "allow", "", trace_id)
        return {"id": ticket_id, "status": "resolved"}

    def leave_summary(self, service_name: str, min_group: int = 3) -> list[dict]:
        """Aggregate-only report for a service account. Groups under min_group are suppressed."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT e.department, COUNT(DISTINCT e.id) AS headcount,"
                " COALESCE(SUM(CASE WHEN r.status = 'pending' THEN 1 END), 0) AS pending_requests"
                " FROM employees e LEFT JOIN leave_requests r ON r.employee_id = e.id GROUP BY e.department"
            ).fetchall()
        self.audit(service_name, service_name, "reports:aggregate", None, "allow", "aggregate only")
        return [dict(r) if r["headcount"] >= min_group else
                {"department": r["department"], "headcount": None, "pending_requests": None} for r in rows]
