import { useCallback } from "react";
import type { ApiClient } from "../api/client";
import { useLoad } from "./useLoad";

export function AuditLog({ api }: { api: ApiClient }) {
  const load = useCallback(() => api.audit(), [api]);
  const { data, error } = useLoad(load);
  return (
    <section>
      <h2>Audit log</h2>
      {error && <p role="alert" className="error">{error}</p>}
      <table>
        <thead><tr><th>Time</th><th>Actor</th><th>Via</th><th>Action</th><th>Target</th><th>Decision</th><th>Reason</th></tr></thead>
        <tbody>
          {data?.map((e) => (
            <tr key={e.id} className={e.decision === "deny" ? "deny" : ""}>
              <td>{e.ts}</td><td>{e.actor}</td><td>{e.via_service ?? "-"}</td><td>{e.action}</td><td>{e.target ?? "-"}</td><td>{e.decision}</td><td>{e.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
