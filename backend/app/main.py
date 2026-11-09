"""FastAPI application. Identity always comes from the verified token or service key, never the body."""
import base64
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import Workflow
from .authz import ROLE_SCOPES, Actor
from .config import Settings
from .db import Database, hash_key, verify_password
from .hr_service import Denied, HRService, InvalidRequest
from .llm import OllamaClient
from .retrieval import Retriever, load_corpus


class LoginBody(BaseModel):
    employee_id: str = Field(max_length=16)
    password: str = Field(max_length=128)


class LeaveBody(BaseModel):
    employee_id: str = Field(max_length=16)
    leave_type: str = Field(max_length=16)
    start_date: str = Field(max_length=10)
    end_date: str = Field(max_length=10)
    reason: str = Field(default="", max_length=500)


class DecisionBody(BaseModel):
    decision: str = Field(max_length=16)
    note: str = Field(default="", max_length=500)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def build_workflow(settings: Settings, db: Database, hr: HRService) -> Workflow:
    corpus = load_corpus()
    if settings.llm_mode == "ollama":
        llm = OllamaClient(settings.ollama_url, settings.chat_model, settings.embed_model)
        return Workflow(db, hr, Retriever(corpus, llm.embed), llm)
    return Workflow(db, hr, Retriever(corpus))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign_token(secret: str, employee_id: str, ttl: int, now: float | None = None) -> str:
    payload = _b64(json.dumps({"sub": employee_id, "exp": int((now or time.time()) + ttl)}).encode())
    return f"{payload}.{_b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())}"


def verify_token(secret: str, token: str, now: float | None = None) -> str | None:
    try:
        payload, signature = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, TypeError):
        return None
    return data["sub"] if data.get("exp", 0) > (now or time.time()) else None


def create_app(settings: Settings | None = None, service: HRService | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.db_path)
    db.init(settings.demo_password)
    hr = service or HRService(db)
    app = FastAPI(title="HR Helpdesk Portal (synthetic data)")
    workflow = build_workflow(settings, db, hr)
    app.state.hr, app.state.db, app.state.settings = hr, db, settings

    @app.exception_handler(Denied)
    async def _denied(_: Request, exc: Denied):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(InvalidRequest)
    async def _invalid(_: Request, exc: InvalidRequest):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def current_actor(authorization: str = Header(default="")) -> Actor:
        employee_id = verify_token(settings.token_secret, authorization.removeprefix("Bearer ").strip())
        profile = hr.profile(employee_id) if employee_id else None
        if profile is None:
            raise HTTPException(401, "Authentication required.")
        return Actor(profile["id"], profile["role"])

    @app.get("/health")
    def health():
        return {"status": "ok", "llm_mode": settings.llm_mode, "data": "synthetic"}

    @app.post("/api/auth/login")
    def login(body: LoginBody):
        with db.connect() as conn:
            row = conn.execute("SELECT password_hash FROM employees WHERE id = ?", (body.employee_id,)).fetchone()
        ok = row is not None and verify_password(body.password, row["password_hash"])
        hr.audit(body.employee_id, None, "auth:login", None, "allow" if ok else "deny")
        if not ok:
            raise HTTPException(401, "Invalid credentials.")
        return {"token": sign_token(settings.token_secret, body.employee_id, settings.token_ttl_seconds),
                "user": hr.profile(body.employee_id)}

    @app.get("/api/me")
    def me(actor: Actor = Depends(current_actor)):
        return {**hr.profile(actor.employee_id), "scopes": sorted(ROLE_SCOPES[actor.role])}

    @app.get("/api/employees/{employee_id}/leave-balance")
    def balance(employee_id: str, actor: Actor = Depends(current_actor)):
        return hr.get_balance(actor, employee_id, uuid.uuid4().hex)

    @app.get("/api/employees/{employee_id}/leave-requests")
    def requests(employee_id: str, actor: Actor = Depends(current_actor)):
        return hr.list_requests(actor, employee_id, uuid.uuid4().hex)

    @app.post("/api/leave-requests", status_code=201)
    def create_request(body: LeaveBody, actor: Actor = Depends(current_actor)):
        return hr.create_request(actor, body.employee_id, body.leave_type, body.start_date, body.end_date,
                                 body.reason, uuid.uuid4().hex)

    @app.get("/api/approvals")
    def approvals(actor: Actor = Depends(current_actor)):
        return hr.pending_approvals(actor, uuid.uuid4().hex)

    @app.post("/api/leave-requests/{request_id}/decision")
    def decide(request_id: int, body: DecisionBody, actor: Actor = Depends(current_actor)):
        return hr.decide_request(actor, request_id, body.decision, body.note, uuid.uuid4().hex)

    @app.get("/api/audit")
    def audit(actor: Actor = Depends(current_actor)):
        return hr.audit_entries(actor, trace_id=uuid.uuid4().hex)

    @app.post("/api/chat")
    def chat(body: ChatBody, actor: Actor = Depends(current_actor)):
        result = workflow.run(actor, body.message)
        result.pop("meta")  # evaluation-only detail stays server side
        return result

    @app.get("/api/escalations")
    def escalations(actor: Actor = Depends(current_actor)):
        return hr.list_escalations(actor, uuid.uuid4().hex)

    @app.post("/api/escalations/{ticket_id}/resolve")
    def resolve(ticket_id: int, actor: Actor = Depends(current_actor)):
        return hr.resolve_escalation(actor, ticket_id, uuid.uuid4().hex)

    @app.get("/api/service/leave-summary")
    def leave_summary(x_service_key: str = Header(default="")):
        with db.connect() as conn:
            row = conn.execute("SELECT name, scopes FROM service_accounts WHERE key_hash = ? AND active = 1"
                               " AND kind = 'external'", (hash_key(x_service_key),)).fetchone()
        if row is None or "reports:aggregate" not in json.loads(row["scopes"]):
            hr.audit("unknown-service", None, "reports:aggregate", None, "deny", "bad or inactive key")
            raise HTTPException(401, "Invalid service key.")
        return hr.leave_summary(row["name"])

    if settings.static_dir and Path(settings.static_dir).is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="ui")
    return app
