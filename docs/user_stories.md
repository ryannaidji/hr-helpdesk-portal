# User stories and acceptance criteria

All people and policies are synthetic. Each criterion names the automated test that checks it.
Paths: `backend/tests/` (pytest) and `frontend/src/` (Vitest).

## Employee

**US-1. Ask a policy question.** As an employee, I want answers with sources so that I can trust them.
- Answer cites the policy section. `test_agents.py::test_policy_answer_is_cited`
- A question the policies do not cover gets an abstention, not a guess. `test_agents.py::test_out_of_corpus_question_abstains`
- A citation to a source that was never retrieved is removed. `test_agents.py::test_hallucinated_citation_is_removed`
- An LLM answer with no valid citation is not shown. `test_agents.py::test_uncited_llm_answer_falls_back_to_extract`
- The UI lists the sources. `components.test.tsx` "renders citations"

**US-2. Check my leave balance.** As an employee, I want to see my balance in chat or in the portal.
- Chat returns my own balance. `test_agents.py::test_own_balance_via_chat`
- I cannot read a colleague's balance by id, by name or by prompt injection. `test_agents.py::test_cross_employee_chat_denied`, `test_api.py::test_idor_returns_403`
- A forbidden id and a nonexistent id give the same response. `test_authz.py::test_unknown_target_is_indistinguishable_from_forbidden`

**US-3. Request leave.** As an employee, I want to file leave through chat or a form.
- Filing creates a pending request and does not change the balance. `test_agents.py::test_agent_files_request_but_cannot_approve`
- Pending days reduce what I can still request. `test_authz.py::test_pending_days_reduce_available_balance`
- Overlapping and past dates are refused. `test_authz.py::test_overlap_and_past_dates_rejected`
- A request body cannot name another employee as requester. `test_api.py::test_body_cannot_spoof_requester`

**US-4. Reach a human for a serious problem.** As an employee reporting harassment or a safety issue, I want a person, not a bot.
- First-person reports escalate. `test_escalation.py::test_first_person_reports_escalate`
- Escalation happens before any LLM call and cannot be overridden by the router. `test_agents.py::test_escalation_overrides_router_and_llm_never_called`
- Safety language is critical even when phrased as a question. `test_escalation.py::test_safety_is_critical_and_not_damped_by_question_form`
- Asking what a policy says does not open a case. `test_escalation.py::test_informational_questions_do_not_escalate`
- The UI shows the escalation and score. `components.test.tsx` "shows an escalation and its score"

## Manager

**US-5. See my team's leave.** As a manager, I want my direct reports' leave, and only theirs.
- Direct reports are readable, other teams are not. `test_authz.py::test_manager_reads_direct_reports_only`
- The agent can read reports for me. `test_agents.py::test_manager_can_read_report_via_agent`
- I do not see the reason on sick, parental or unpaid requests. `test_authz.py::test_manager_cannot_see_reason_on_hr_routed_request`

**US-6. Approve leave.** As a manager, I want to decide my team's ordinary leave requests.
- Approval deducts the balance exactly once. `test_authz.py::test_approval_deducts_once`
- I cannot decide HR-routed requests or another team's. `test_authz.py::test_manager_cannot_decide_hr_routed_or_other_team`
- The full flow works through the API. `test_api.py::test_full_approval_flow`
- The UI sends my decision and refreshes. `components.test.tsx` "sends the decision and reloads"

## HR

**US-7. Oversee sensitive decisions.** As HR, I want sensitive leave routed to me and no self-approval.
- Sensitive types and long absences require HR. `test_authz.py::test_leave_rules`
- Nobody approves their own request, HR included. `test_authz.py::test_no_self_approval_even_for_hr`
- An agent can never approve. `test_authz.py::test_agent_can_never_decide`

**US-8. Audit access.** As HR, I want a tamper-resistant record of every access decision.
- Allowed and denied attempts are recorded. `test_authz.py::test_every_decision_is_audited`
- The table rejects UPDATE and DELETE. `test_authz.py::test_audit_log_is_append_only`
- Only HR reads it. `test_authz.py::test_audit_read_is_hr_only`
- Chat text is not copied into the log. `test_agents.py::test_chat_is_audited_without_message_text`
- Agent actions name the service account used. `test_agents.py::test_delegated_actor_is_recorded`

**US-9. Work escalations.** As HR, I want a private, prioritised queue. `test_api.py::test_escalation_queue_is_hr_only_and_resolvable`

## Platform owner

**US-10. Keep agents least-privilege.** As the owner, I want an agent to hold no more access than its task needs.
- Agent permissions are the intersection of user and service account. `test_authz.py::test_delegation_is_intersection`
- HR cannot use the chat agent for org-wide reads. `test_agents.py::test_hr_user_cannot_use_agent_for_org_wide_read`
- An LLM-chosen target is still authorized. `test_agents.py::test_llm_target_cannot_bypass_authz`
- Restricted documents never reach the LLM. `test_agents.py::test_restricted_chunks_never_reach_llm`

**US-11. Manage service credentials.** As an operator, I want to rotate or disable a key at once.
- Rotation kills the old key, disabling kills the current one, and the report is aggregate-only. `test_api.py::test_service_key_lifecycle`
