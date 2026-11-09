# Operations runbook

Demo scope: one process and one SQLite file, over synthetic data.

## Start and health

    cd backend && uvicorn app.asgi:app --port 8000
    curl localhost:8000/health

| Variable | Default | Purpose |
|---|---|---|
| `HR_DB_PATH` | `backend/data/hr.db` | SQLite file |
| `HR_TOKEN_SECRET` | random per process | Session signing. Set it, or restarts sign everyone out |
| `HR_LLM_MODE` | `rules` | `rules` needs no LLM; `ollama` uses local models |
| `HR_CHAT_MODEL` | `qwen2.5:3b` | Ollama chat model |
| `HR_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `HR_DEMO_PASSWORD` | `demo-only` | Password for the seeded fictional users |
| `HR_STATIC_DIR` | empty | Serve the built frontend, e.g. `../frontend/dist` |

## Service accounts

| Account | Kind | Scopes | Key |
|---|---|---|---|
| `svc-policy-agent` | internal | `policy:read` | none, in-process only |
| `svc-hr-action-agent` | internal | `leave:read:self`, `leave:read:reports`, `leave:request:self` | none, in-process only |
| `svc-escalation-agent` | internal | `escalation:create` | none, in-process only |
| `svc-leave-report` | external | `reports:aggregate` | hashed in the database |

    python -m app.admin list
    python -m app.admin rotate svc-leave-report    # prints the new key once
    python -m app.admin disable svc-leave-report
    python -m app.admin enable svc-leave-report

Rotate external keys on a schedule and whenever someone with access leaves. Adding a scope to an agent changes
what the model-driven path can reach, so make that change in code with a test, and rerun the authorization evaluation.

## Backup and restore

SQLite: stop the app, or use `sqlite3 hr.db ".backup backup.db"`. To restore, stop the app, replace the file, start it.
The audit log has no retention job: it grows until someone archives it. Archiving needs the triggers dropped on purpose,
so do it only as a recorded maintenance step.

## Changing policies

Edit or add Markdown in `backend/data/policies/` with front matter `title` and `audience` (`all`, `manager` or `hr`).
Each `##` heading becomes a citable section. The index is built at startup, so restart afterwards. If you rename a
heading, update its citation key in `evals/data.py`.

## Release checks

`ruff check .`, `pytest -q` and the no-LLM eval gate in `backend/`; `npm run lint`, `npm run typecheck`, `npm test`
and `npm run build` in `frontend/`. A leak rate above zero blocks a release, and so does a negative control that
stops detecting leaks.
