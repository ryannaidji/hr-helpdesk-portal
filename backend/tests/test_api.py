from app.admin import rotate, set_active
from app.main import sign_token, verify_token


def test_login_and_me(client):
    res = client.post("/api/auth/login", json={"employee_id": "E1005", "password": "pw"})
    assert res.status_code == 200
    me = client.get("/api/me", headers={"Authorization": f"Bearer {res.json()['token']}"}).json()
    assert me["role"] == "employee" and "audit:read" not in me["scopes"]


def test_bad_password_rejected(client):
    assert client.post("/api/auth/login", json={"employee_id": "E1005", "password": "no"}).status_code == 401


def test_no_token_rejected(client):
    assert client.get("/api/employees/E1005/leave-balance").status_code == 401


def test_tampered_and_expired_tokens_rejected():
    token = sign_token("s", "E1005", 60, now=1000)
    assert verify_token("s", token, now=1001) == "E1005"
    assert verify_token("s", token, now=2000) is None
    assert verify_token("other", token, now=1001) is None
    assert verify_token("s", "garbage", now=1001) is None


def test_idor_returns_403(client, auth):
    assert client.get("/api/employees/E1006/leave-balance", headers=auth("E1005")).status_code == 403
    assert client.get("/api/employees/E1006/leave-requests", headers=auth("E1005")).status_code == 403


def test_body_cannot_spoof_requester(client, auth):
    body = {"employee_id": "E1006", "leave_type": "annual", "start_date": "2032-01-05", "end_date": "2032-01-06"}
    assert client.post("/api/leave-requests", json=body, headers=auth("E1005")).status_code == 403


def test_full_approval_flow(client, auth):
    body = {"employee_id": "E1005", "leave_type": "annual", "start_date": "2032-01-05", "end_date": "2032-01-06"}
    created = client.post("/api/leave-requests", json=body, headers=auth("E1005")).json()
    queue = client.get("/api/approvals", headers=auth("E1003")).json()
    assert created["id"] in [r["id"] for r in queue]
    decided = client.post(f"/api/leave-requests/{created['id']}/decision", json={"decision": "approved"},
                          headers=auth("E1003"))
    assert decided.json()["status"] == "approved"


def test_employee_has_no_approval_queue_or_audit(client, auth):
    assert client.get("/api/approvals", headers=auth("E1005")).status_code == 403
    assert client.get("/api/audit", headers=auth("E1005")).status_code == 403


def test_service_key_lifecycle(client):
    db = client.app.state.db
    url = "/api/service/leave-summary"
    assert client.get(url, headers={"X-Service-Key": "nope"}).status_code == 401
    assert client.get(url).status_code == 401  # unset key hashes never match a NULL key_hash
    first = rotate(db, "svc-leave-report")
    res = client.get(url, headers={"X-Service-Key": first})
    assert res.status_code == 200
    assert "CANARY" not in res.text and "E100" not in res.text
    assert {r["department"]: r["headcount"] for r in res.json()}["People"] is None  # n=2 suppressed
    second = rotate(db, "svc-leave-report")
    assert client.get(url, headers={"X-Service-Key": first}).status_code == 401
    set_active(db, "svc-leave-report", False)
    assert client.get(url, headers={"X-Service-Key": second}).status_code == 401


def test_chat_endpoint_hides_eval_meta_and_uses_token_identity(client, auth):
    res = client.post("/api/chat", json={"message": "What is my leave balance?"}, headers=auth("E1005")).json()
    assert "13.75" in res["answer"] and "meta" not in res


def test_chat_requires_auth_and_limits_length(client, auth):
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert client.post("/api/chat", json={"message": "x" * 2001}, headers=auth("E1005")).status_code == 422


def test_escalation_queue_is_hr_only_and_resolvable(client, auth):
    out = client.post("/api/chat", json={"message": "My manager is harassing me"}, headers=auth("E1005")).json()
    ticket = out["escalation"]["ticket_id"]
    assert client.get("/api/escalations", headers=auth("E1003")).status_code == 403
    queue = client.get("/api/escalations", headers=auth("E1002")).json()
    assert queue[0]["id"] == ticket and queue[0]["level"] == "high"
    assert client.post(f"/api/escalations/{ticket}/resolve", headers=auth("E1005")).status_code == 403
    assert client.post(f"/api/escalations/{ticket}/resolve", headers=auth("E1002")).json()["status"] == "resolved"
