import sqlite3

import pytest

from app.authz import Actor, ServiceAccount, decide_on_employee
from app.hr_service import Denied, HRService, InvalidRequest
from app.leave import required_approver, working_days

from .conftest import EMPLOYEE, HR_USER, MANAGER, OTHER_MANAGER, PEER

AGENT = ServiceAccount("svc-hr-action-agent", frozenset({"leave:read:self", "leave:read:reports", "leave:request:self"}))
FUTURE = ("2032-01-05", "2032-01-06")


def test_employee_reads_only_self(hr):
    assert hr.get_balance(EMPLOYEE, "E1005")["balances"]["annual"] == 13.75
    with pytest.raises(Denied):
        hr.get_balance(EMPLOYEE, "E1006")


def test_manager_reads_direct_reports_only(hr):
    assert hr.get_balance(MANAGER, "E1005")
    with pytest.raises(Denied):
        hr.get_balance(MANAGER, "E1008")


def test_hr_reads_anyone(hr):
    assert hr.get_balance(HR_USER, "E1010")


def test_delegation_is_intersection():
    hr_via_agent = Actor("E1002", "hr", AGENT)
    assert not decide_on_employee(hr_via_agent, "leave:read", "E1010", "E1004").allowed
    assert decide_on_employee(Actor("E1002", "hr"), "leave:read", "E1010", "E1004").allowed
    assert not decide_on_employee(Actor("E1005", "employee", AGENT), "leave:read", "E1006", "E1003").allowed


def test_agent_can_never_decide(hr):
    request_id = hr.list_requests(HR_USER, "E1006")[0]["id"]
    with pytest.raises(Denied):
        hr.decide_request(Actor("E1003", "manager", AGENT), request_id, "approved")


def test_unknown_target_is_indistinguishable_from_forbidden(hr):
    with pytest.raises(Denied) as forbidden:
        hr.get_balance(EMPLOYEE, "E1006")
    with pytest.raises(Denied) as missing:
        hr.get_balance(EMPLOYEE, "E9999")
    assert str(forbidden.value) == str(missing.value)


def test_manager_cannot_see_reason_on_hr_routed_request(hr):
    assert hr.list_requests(MANAGER, "E1005")[0]["reason"] is None  # sick leave
    assert "CANARY" in hr.list_requests(MANAGER, "E1006")[0]["reason"]  # annual leave
    assert "CANARY" in hr.list_requests(HR_USER, "E1005")[0]["reason"]
    assert "CANARY" in hr.list_requests(EMPLOYEE, "E1005")[0]["reason"]


def test_cannot_request_for_someone_else(hr):
    with pytest.raises(Denied):
        hr.create_request(MANAGER, "E1005", "annual", *FUTURE)


def test_approval_deducts_once(hr):
    created = hr.create_request(EMPLOYEE, "E1005", "annual", *FUTURE)
    assert created["status"] == "pending" and created["required_approver"] == "manager"
    assert hr.get_balance(EMPLOYEE, "E1005")["balances"]["annual"] == 13.75  # no change until approved
    hr.decide_request(MANAGER, created["id"], "approved")
    assert hr.get_balance(EMPLOYEE, "E1005")["balances"]["annual"] == 11.75
    with pytest.raises(InvalidRequest):
        hr.decide_request(MANAGER, created["id"], "approved")
    assert hr.get_balance(EMPLOYEE, "E1005")["balances"]["annual"] == 11.75


def test_no_self_approval_even_for_hr(hr):
    created = hr.create_request(HR_USER, "E1002", "annual", *FUTURE)
    with pytest.raises(Denied):
        hr.decide_request(HR_USER, created["id"], "approved")


def test_manager_cannot_decide_hr_routed_or_other_team(hr):
    sick = hr.list_requests(HR_USER, "E1005")[0]["id"]
    with pytest.raises(Denied):
        hr.decide_request(MANAGER, sick, "approved")
    annual = hr.list_requests(HR_USER, "E1006")[0]["id"]
    with pytest.raises(Denied):
        hr.decide_request(OTHER_MANAGER, annual, "approved")


def test_pending_days_reduce_available_balance(hr):
    hr.create_request(PEER, "E1006", "sick", "2032-02-02", "2032-02-05")  # 4 of 4.75
    with pytest.raises(InvalidRequest, match="Insufficient"):
        hr.create_request(PEER, "E1006", "sick", "2032-03-01", "2032-03-02")


def test_overlap_and_past_dates_rejected(hr):
    with pytest.raises(InvalidRequest, match="overlaps"):
        hr.create_request(EMPLOYEE, "E1005", "annual", "2031-02-04", "2031-02-05")
    with pytest.raises(InvalidRequest, match="past"):
        hr.create_request(EMPLOYEE, "E1005", "annual", "2020-01-06", "2020-01-07")


def test_every_decision_is_audited(hr):
    hr.get_balance(EMPLOYEE, "E1005", "t1")
    with pytest.raises(Denied):
        hr.get_balance(EMPLOYEE, "E1006", "t2")
    rows = {r["trace_id"]: r for r in hr.audit_entries(HR_USER)}
    assert rows["t1"]["decision"] == "allow"
    assert rows["t2"]["decision"] == "deny" and rows["t2"]["target"] == "E1006"


def test_audit_log_is_append_only(hr, db):
    hr.get_balance(EMPLOYEE, "E1005")
    with db.connect() as conn, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log")
    with db.connect() as conn, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET decision = 'allow'")


def test_audit_read_is_hr_only(hr):
    for actor in (EMPLOYEE, MANAGER):
        with pytest.raises(Denied):
            hr.audit_entries(actor)


def test_negative_control_flag_really_disables_checks(db):
    assert HRService(db, enforce=False).get_balance(EMPLOYEE, "E1006")["balances"]["annual"] == 11.25


def test_leave_rules():
    assert working_days("2032-01-02", "2032-01-05") == 2  # Fri..Mon spans a weekend
    assert required_approver("annual", 10) == "manager"
    assert required_approver("annual", 11) == "hr"
    assert required_approver("sick", 1) == "hr"
