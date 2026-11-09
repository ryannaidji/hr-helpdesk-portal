"""Authorization decisions: small pure functions, enforced server side.

A human's role grants scopes. A service account has its own scope ceiling. When a service account
acts on behalf of a user, the effective permission is the INTERSECTION of the two: an agent can
never do something its user cannot, and a user cannot get more through an agent than the agent holds.
"""
from dataclasses import dataclass

_BASE = {"policy:read", "leave:read:self", "leave:request:self", "escalation:create"}

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "employee": frozenset(_BASE),
    "manager": frozenset(_BASE | {"leave:read:reports", "leave:decide:reports"}),
    "hr": frozenset(_BASE | {"leave:read:all", "leave:decide:all", "audit:read", "escalation:read"}),
}


@dataclass(frozen=True)
class ServiceAccount:
    name: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class Actor:
    employee_id: str
    role: str
    via: ServiceAccount | None = None  # set when an agent acts on this user's behalf

    def delegate_to(self, service: ServiceAccount) -> "Actor":
        return Actor(self.employee_id, self.role, service)

    @property
    def effective_scopes(self) -> frozenset[str]:
        scopes = ROLE_SCOPES.get(self.role, frozenset())
        return scopes & self.via.scopes if self.via else scopes


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def relation(actor_id: str, target_id: str, target_manager_id: str | None) -> str:
    if actor_id == target_id:
        return "self"
    return "reports" if target_manager_id == actor_id else "other"


def decide_scoped(actor: Actor, scope: str) -> Decision:
    """Decide an action that has no target employee."""
    if scope in actor.effective_scopes:
        return Decision(True, f"has {scope}")
    return Decision(False, f"missing {scope}")


def decide_on_employee(actor: Actor, action: str, target_id: str, target_manager_id: str | None) -> Decision:
    """Decide an action on one employee's data. action is leave:read, leave:request or leave:decide."""
    rel = relation(actor.employee_id, target_id, target_manager_id)
    if action == "leave:decide" and rel == "self":
        return Decision(False, "separation of duties: cannot decide own request")
    tiers = {"self": ["self", "all"], "reports": ["reports", "all"], "other": ["all"]}[rel]
    for tier in tiers:
        if f"{action}:{tier}" in actor.effective_scopes:
            return Decision(True, f"has {action}:{tier}")
    return Decision(False, f"no {action} permission for relation {rel}")
