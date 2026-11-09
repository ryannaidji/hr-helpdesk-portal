# Incident runbook

This is a portfolio project over synthetic data and has never run in production. These procedures are
written against what the code really provides; the commands exist, but no real incident has tested them.

Severity: **SEV1** suspected cross-employee data exposure or audit tampering. **SEV2** approvals or
escalations not working. **SEV3** degraded answers (Ollama down, poor quality).

## 1. Suspected data exposure (SEV1)

1. Contain: stop the API. If one integration is implicated, disable only it: `python -m app.admin disable svc-leave-report`.
2. Preserve: copy `hr.db` before anything else. The audit log cannot be altered through SQL while the triggers exist.
3. Investigate, using `sqlite3 hr.db`:
   - Unusual denials: `SELECT actor, COUNT(*) FROM audit_log WHERE decision='deny' GROUP BY actor ORDER BY 2 DESC;`
   - What an actor reached: `SELECT ts, via_service, action, target, decision, reason FROM audit_log WHERE actor='E1005' ORDER BY id;`
   - Any bypass marker, which must return zero rows: `SELECT * FROM audit_log WHERE decision='allow_unenforced';`
   - Reads across teams: join `audit_log.target` to `employees.manager_id` and look for `allow` rows outside the actor's team.
4. Reproduce: `cd backend && python -m evals.run_eval --mode rules --out /tmp/check.json --thresholds evals/thresholds.json`.
5. Fix forward: add the failing case to `evals/data.py` or the REST matrix before changing the code.
6. Rotate the token secret (`HR_TOKEN_SECRET`), which signs every session out, and rotate external keys.
7. Write up: timeline, data affected, root cause, the test that now covers it.

## 2. Credential compromise (SEV1)

- Service key: `python -m app.admin rotate svc-leave-report`. The old key stops working immediately and the new one prints once.
- Signing secret: change `HR_TOKEN_SECRET` and restart.
- Then review the audit log for that actor since the suspected time of compromise.

## 3. Audit log writes failing (SEV1)

Authorization records its audit row before data is read, so a failing audit write stops the request with a 500.
Treat this as fail-closed behaviour and do not remove it. Check disk space and file permissions on `HR_DB_PATH`.

## 4. Escalations not reaching HR (SEV2)

Check the queue: `SELECT id, score, level, status, created_at FROM escalations ORDER BY id DESC LIMIT 20;`.
Scoring runs without an LLM, so an Ollama outage does not stop it. Staff should use the direct HR contact until this is resolved.
**This system has no paging.** A critical ticket waits in the queue until someone opens it, so real use would need an alerting integration first.

## 5. Ollama down or slow (SEV3)

Symptom: `router_source` values of `rules_fallback` and slow chats. The workflow degrades to the keyword router and
extractive answers. Check `curl localhost:11434/api/tags`, confirm the models are pulled, restart Ollama.
If embeddings are unavailable at startup in `ollama` mode the app fails to start. Set `HR_LLM_MODE=rules` to restore service.

## 6. Bad or wrong policy answers (SEV3)

Check the answer's citation against the file in `backend/data/policies/`. Correct the policy text if it is wrong.
Otherwise add the question to `POLICY_QA` in `evals/data.py` and rerun the evaluation before changing prompts or models.
