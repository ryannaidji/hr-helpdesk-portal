import { useCallback } from "react";
import type { ApiClient } from "../api/client";
import { useLoad } from "./useLoad";

export function Approvals({ api }: { api: ApiClient }) {
  const load = useCallback(() => api.approvals(), [api]);
  const { data, error, reload, setError } = useLoad(load);

  function decide(id: number, decision: "approved" | "rejected") {
    api.decide(id, decision).then(reload).catch((e: Error) => setError(e.message));
  }

  return (
    <section>
      <h2>Awaiting your approval</h2>
      {error && <p role="alert" className="error">{error}</p>}
      {data?.length === 0 && <p>Nothing is waiting for you.</p>}
      <table>
        <thead><tr><th>Employee</th><th>Type</th><th>Dates</th><th>Length</th><th>Decision</th></tr></thead>
        <tbody>
          {data?.map((r) => (
            <tr key={r.id}>
              <td>{r.employee_name}</td><td>{r.leave_type}</td><td>{r.start_date} to {r.end_date}</td><td>{r.days} days</td>
              <td>
                <button onClick={() => decide(r.id, "approved")}>Approve</button>{" "}
                <button onClick={() => decide(r.id, "rejected")}>Reject</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
