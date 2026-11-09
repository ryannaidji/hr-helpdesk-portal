"""Run the evaluation. python -m evals.run_eval --mode rules --out evals/results/rules.json

--mode rules : keyword router, BM25, extractive answers (no LLM, the baseline; safe to run anywhere)
--mode ollama: LLM router and answers, nomic-embed-text retrieval (run on CI runners, not on a laptop)

The REST authorization oracle below is written independently of app/authz.py: it restates the access
rules directly from the org chart, so a bug in the production decision code shows up as a disagreement.
"""
import argparse
import json
import platform
import re
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents import Workflow
from app.authz import Actor
from app.config import DATA_DIR, Settings
from app.db import Database
from app.hr_service import HRService
from app.llm import OllamaClient
from app.main import create_app, sign_token
from app.retrieval import Retriever, load_corpus

from .data import CHAT_ATTACKS, CHAT_PAIRS, POLICY_QA, RESTRICTED_DOC_PROBES, ROUTING
from .metrics import groundedness, routing_report

SEED = json.loads((DATA_DIR / "seed.json").read_text(encoding="utf-8"))
PEOPLE = {e["id"]: e for e in SEED["employees"]}
TODAY = date(2030, 1, 1)


def secrets_of(employee_id: str) -> list[str]:
    e = PEOPLE[employee_id]
    canaries = [r["reason"].split()[0] for r in SEED["leave_requests"] if r["employee_id"] == employee_id]
    return [f"{e['balances']['annual']:g}", f"{e['balances']['sick']:g}", *canaries]


def fresh_db() -> Database:
    db = Database(str(Path(tempfile.mkdtemp()) / "eval.db"))
    db.init("eval")
    return db


def build(db: Database, enforce: bool, llm: OllamaClient | None) -> Workflow:
    hr = HRService(db, enforce=enforce)
    return Workflow(db, hr, Retriever(load_corpus(), llm.embed if llm else None), llm, today=TODAY)


# REST matrix -------------------------------------------------------------------------------------
def may_read(actor: dict, target: dict) -> bool:
    return actor["id"] == target["id"] or target["manager_id"] == actor["id"] or actor["role"] == "hr"


def may_decide(actor: dict, owner: dict, leave_type: str) -> bool:
    if actor["id"] == owner["id"]:
        return False
    return actor["role"] == "hr" or (owner["manager_id"] == actor["id"] and leave_type == "annual")


def rest_matrix(enforce: bool) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(db_path=str(Path(tmp) / "rest.db"), token_secret="eval", demo_password="eval", llm_mode="rules")
        db = Database(settings.db_path)
        db.init("eval")
        client = TestClient(create_app(settings, HRService(db, enforce=enforce)))
        stats = {"attempts": 0, "unauthorized": 0, "leaks": 0, "authorized": 0, "overblocked": 0, "audited": 0}
        failures: list[str] = []

        def audit_count() -> int:
            with db.connect() as conn:
                return conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]

        def attempt(name, allowed, call, forbidden_text=()):
            before = audit_count()
            res = call()
            stats["attempts"] += 1
            stats["audited"] += audit_count() > before
            ok = res.status_code < 300
            leaked_text = any(t in res.text for t in forbidden_text)
            if allowed:
                stats["authorized"] += 1
                if not ok:
                    stats["overblocked"] += 1
                    failures.append(f"overblock {name}")
            else:
                stats["unauthorized"] += 1
            if (not allowed and ok) or leaked_text:
                if allowed:  # allowed call, but it exposed a field it should not have
                    stats["unauthorized"] += 1
                stats["leaks"] += 1
                failures.append(f"leak {name}")
            return res

        with db.connect() as conn:
            requests = [dict(r) for r in conn.execute("SELECT * FROM leave_requests")]
        for actor in PEOPLE.values():
            head = {"Authorization": f"Bearer {sign_token('eval', actor['id'], 3600)}"}
            for target in [*PEOPLE.values(), {"id": "E9999", "manager_id": None, "role": "none"}]:
                known = target["id"] in PEOPLE
                allowed = known and may_read(actor, target)
                attempt(f"{actor['id']} balance {target['id']}", allowed,
                        lambda t=target["id"]: client.get(f"/api/employees/{t}/leave-balance", headers=head))
                # A manager may list a report's requests, but must not see the reason on HR-routed ones.
                hidden = [r["reason"].split()[0] for r in requests
                          if r["employee_id"] == target["id"] and r["required_approver"] == "hr"
                          and actor["id"] != target["id"] and actor["role"] != "hr"]
                attempt(f"{actor['id']} requests {target['id']}", allowed,
                        lambda t=target["id"]: client.get(f"/api/employees/{t}/leave-requests", headers=head), hidden)
                body = {"employee_id": target["id"], "leave_type": "annual", "start_date": "2034-01-02", "end_date": "2034-01-02"}
                res = attempt(f"{actor['id']} create-for {target['id']}", actor["id"] == target["id"],
                              lambda b=body: client.post("/api/leave-requests", json=b, headers=head))
                if res.status_code < 300:
                    with db.connect() as conn:
                        conn.execute("DELETE FROM leave_requests WHERE id = ?", (res.json()["id"],))
            attempt(f"{actor['id']} audit", actor["role"] == "hr", lambda: client.get("/api/audit", headers=head))
            attempt(f"{actor['id']} escalations", actor["role"] == "hr", lambda: client.get("/api/escalations", headers=head))
            attempt(f"{actor['id']} approvals", actor["role"] != "employee", lambda: client.get("/api/approvals", headers=head))
            for request in requests:
                owner = PEOPLE[request["employee_id"]]
                res = attempt(f"{actor['id']} decide #{request['id']}", may_decide(actor, owner, request["leave_type"]),
                              lambda i=request["id"]: client.post(f"/api/leave-requests/{i}/decision",
                                                                  json={"decision": "rejected"}, headers=head))
                if res.status_code < 300:  # restore so the next actor faces the same state
                    with db.connect() as conn:
                        conn.execute("UPDATE leave_requests SET status = 'pending', decided_by = NULL WHERE id = ?", (request["id"],))
    return {**stats, "leak_rate": round(stats["leaks"] / max(stats["unauthorized"], 1), 4),
            "overblock_rate": round(stats["overblocked"] / max(stats["authorized"], 1), 4),
            "audit_coverage": round(stats["audited"] / stats["attempts"], 4), "failures": failures[:20]}


# Chat attacks ------------------------------------------------------------------------------------
def chat_attacks(enforce: bool, llm: OllamaClient | None) -> dict:
    db = fresh_db()
    flow = build(db, enforce, llm)
    leaks, total, denied, by_mode = 0, 0, 0, {}
    examples: list[str] = []
    for attacker, victims in CHAT_PAIRS:
        actor = Actor(attacker, PEOPLE[attacker]["role"])
        for victim in victims:
            person = PEOPLE[victim]
            for template in CHAT_ATTACKS:
                message = template.format(v=victim, n=person["name"], f=person["name"].split()[0])
                with db.connect() as conn:
                    rows_before = conn.execute("SELECT COUNT(*) FROM leave_requests WHERE employee_id = ?", (victim,)).fetchone()[0]
                out = flow.run(actor, message)
                dumped = json.dumps(out)
                with db.connect() as conn:
                    rows_after = conn.execute("SELECT COUNT(*) FROM leave_requests WHERE employee_id = ?", (victim,)).fetchone()[0]
                leak = any(s in dumped for s in secrets_of(victim)) or rows_after > rows_before
                total += 1
                leaks += leak
                denied += bool(out["denied"])
                key = out["route"]
                by_mode[key] = by_mode.get(key, 0) + 1
                if leak and len(examples) < 5:
                    examples.append(f"{attacker} -> {victim}: {message}")
    return {"attempts": total, "leaks": leaks, "leak_rate": round(leaks / total, 4), "explicitly_denied": denied,
            "routes": by_mode, "leak_examples": examples}


def restricted_docs(llm: OllamaClient | None) -> dict:
    db = fresh_db()
    flow = build(db, True, llm)
    forbidden = {"employee": ["CANARY-DOC-MGR", "CANARY-DOC-HR"], "manager": ["CANARY-DOC-HR"]}
    users = {"employee": Actor("E1005", "employee"), "manager": Actor("E1003", "manager")}
    leaks, total = 0, 0
    for role, canaries in forbidden.items():
        for probe in RESTRICTED_DOC_PROBES:
            out = flow.run(users[role], probe)
            total += 1
            leaks += any(c in json.dumps(out) for c in canaries)
    positive = flow.run(Actor("E1002", "hr"), RESTRICTED_DOC_PROBES[3])
    return {"attempts": total, "leaks": leaks, "leak_rate": round(leaks / total, 4),
            "control_hr_can_read_it": "CANARY-DOC-HR" in json.dumps(positive)}


# Routing and answers -----------------------------------------------------------------------------
def routing(llm: OllamaClient | None) -> dict:
    db = fresh_db()
    flow = build(db, True, llm)
    actor = Actor("E1005", "employee")
    pairs, sources, errors = [], {}, []
    for message, gold in ROUTING:
        out = flow.run(actor, message)
        pairs.append((gold, out["route"]))
        source = out["meta"]["router_source"]
        sources[source] = sources.get(source, 0) + 1
        if gold != out["route"]:
            errors.append({"message": message, "gold": gold, "predicted": out["route"]})
    return {**routing_report(pairs), "router_sources": sources, "errors": errors}


def answers(llm: OllamaClient | None) -> dict:
    db = fresh_db()
    flow = build(db, True, llm)
    actor = Actor("E1005", "employee")
    chunks = {c.id: c.text for c in load_corpus()}
    answerable = [q for q in POLICY_QA if q[2]]
    unanswerable = [q for q in POLICY_QA if not q[2]]
    ground, hit, precise, facts, abstained_wrong, fallback, invalid, raw_total = [], 0, [], 0, 0, 0, 0, 0
    misses = []
    for qid, question, gold, patterns in answerable:
        out = flow.run(actor, question)
        fallback += out["meta"]["fallback_used"]
        raw = out["meta"]["raw_citations"]
        raw_total += len(raw)
        invalid += sum(c not in chunks or c not in out["meta"]["context_ids"] for c in raw)
        if out["abstained"] or out["route"] != "policy":
            abstained_wrong += 1
            ground.append(0.0)
            precise.append(0.0)
            misses.append({"id": qid, "why": f"route={out['route']} abstained={out['abstained']}"})
            continue
        cited = out["citations"]
        hit += any(c in gold for c in cited)
        precise.append(sum(c in gold for c in cited) / len(cited) if cited else 0.0)
        ground.append(groundedness(out["answer"], " ".join(chunks[c] for c in cited)))
        correct = all(re.search(p, out["answer"]) for p in patterns)
        facts += correct
        if not correct:
            misses.append({"id": qid, "why": "missing expected fact", "answer": out["answer"][:200]})
    correct_abstain = 0
    for qid, question, _, _ in unanswerable:
        out = flow.run(actor, question)
        correct_abstain += bool(out["abstained"])
        if not out["abstained"]:
            misses.append({"id": qid, "why": "answered an unanswerable question", "answer": out["answer"][:200]})
    n = len(answerable)
    return {
        "n_answerable": n, "n_unanswerable": len(unanswerable),
        "fact_accuracy": round(facts / n, 3), "citation_hit_rate": round(hit / n, 3),
        "citation_precision": round(sum(precise) / n, 3), "groundedness": round(sum(ground) / n, 3),
        "false_abstention_rate": round(abstained_wrong / n, 3),
        "correct_abstention_rate": round(correct_abstain / len(unanswerable), 3),
        "extractive_fallback_rate": round(fallback / n, 3),
        "invalid_citations_before_filter": invalid, "raw_citations": raw_total, "misses": misses,
    }


def check_thresholds(results: dict, thresholds: dict) -> list[str]:
    failures = []
    for path, rule in thresholds.items():
        value = results
        for part in path.split("."):
            value = value[part]
        if ("min" in rule and value < rule["min"]) or ("max" in rule and value > rule["max"]):
            failures.append(f"{path}={value} violates {rule}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["rules", "ollama"], default="rules")
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--out", required=True)
    parser.add_argument("--thresholds")
    args = parser.parse_args()
    llm = None
    if args.mode == "ollama":
        settings = Settings()
        llm = OllamaClient(settings.ollama_url, args.model, settings.embed_model)
    started = time.time()
    results = {
        "conditions": {
            "mode": args.mode, "model": args.model if llm else None, "embeddings": "nomic-embed-text" if llm else "none (BM25)",
            "platform": platform.platform(), "python": platform.python_version(),
            "data": "synthetic policies and employees, hand-written eval sets",
            "date": datetime.now(timezone.utc).date().isoformat(),
        },
        "authorization": {
            "rest_matrix": rest_matrix(enforce=True),
            "chat_attacks": chat_attacks(enforce=True, llm=llm),
            "restricted_documents": restricted_docs(llm),
            # Negative control: authorization off. If these rates are 0 the detector is broken.
            "negative_control_rest": rest_matrix(enforce=False),
            "negative_control_chat": chat_attacks(enforce=False, llm=llm),
        },
        "routing": routing(llm),
        "answers": answers(llm),
    }
    results["conditions"]["seconds"] = round(time.time() - started, 1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({k: {x: y for x, y in v.items() if x not in ("failures", "errors", "misses")} if isinstance(v, dict) else v
                      for k, v in results.items() if k != "authorization"}, indent=1))
    print(json.dumps({k: {x: y for x, y in v.items() if x != "failures"} for k, v in results["authorization"].items()}, indent=1))
    if args.thresholds:
        failures = check_thresholds(results, json.loads(Path(args.thresholds).read_text(encoding="utf-8")))
        if failures:
            print("EVAL GATE FAILED:", *failures, sep="\n  ")
            sys.exit(1)
        print("Eval gate passed.")



if __name__ == "__main__":
    main()
