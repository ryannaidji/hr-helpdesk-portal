import { useCallback, useState, type FormEvent } from "react";
import type { ApiClient } from "../api/client";
import type { User } from "../api/types";
import { useLoad } from "./useLoad";

export function MyLeave({ api, user }: { api: ApiClient; user: User }) {
  const load = useCallback(
    () => Promise.all([api.balance(user.id), api.requests(user.id)]),
    [api, user.id],
  );
  const { data, error, reload, setError } = useLoad(load);
  const [form, setForm] = useState({ leave_type: "annual", start_date: "", end_date: "", reason: "" });

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createRequest({ ...form, employee_id: user.id });
      setForm({ ...form, start_date: "", end_date: "", reason: "" });
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const [balance, requests] = data ?? [null, []];
  return (
    <section>
      <h2>My leave</h2>
      {error && <p role="alert" className="error">{error}</p>}
      {balance && (
        <div className="row stats">
          {Object.entries(balance.balances).map(([kind, days]) => (
            <div className="card" key={kind}><strong>{days}</strong> {kind} days</div>
          ))}
        </div>
      )}
      <form className="card grid" onSubmit={submit}>
        <label>Type
          <select value={form.leave_type} onChange={(e) => setForm({ ...form, leave_type: e.target.value })}>
            {["annual", "sick", "parental", "unpaid"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>Start<input type="date" required value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></label>
        <label>End<input type="date" required value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></label>
        <label>Reason (optional)<input value={form.reason} maxLength={500} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
        <button>Request leave</button>
      </form>
      <table>
        <thead><tr><th>Type</th><th>From</th><th>To</th><th>Days</th><th>Status</th><th>Approver</th></tr></thead>
        <tbody>
          {requests.map((r) => (
            <tr key={r.id}><td>{r.leave_type}</td><td>{r.start_date}</td><td>{r.end_date}</td><td>{r.days}</td><td>{r.status}</td><td>{r.required_approver}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
