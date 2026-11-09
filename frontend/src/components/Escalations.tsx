import { useCallback } from "react";
import type { ApiClient } from "../api/client";
import { useLoad } from "./useLoad";

export function Escalations({ api }: { api: ApiClient }) {
  const load = useCallback(() => api.escalations(), [api]);
  const { data, error, reload, setError } = useLoad(load);
  return (
    <section>
      <h2>Escalations</h2>
      {error && <p role="alert" className="error">{error}</p>}
      {data?.length === 0 && <p>No escalations.</p>}
      {data?.map((t) => (
        <article className="card" key={t.id}>
          <p><strong>#{t.id}</strong> {t.employee_id}: score {t.score} ({t.level}), {t.status}</p>
          <p>{t.message}</p>
          <p className="meta">{t.reasons.join(", ")}</p>
          {t.status === "open" && (
            <button onClick={() => api.resolveEscalation(t.id).then(reload).catch((e: Error) => setError(e.message))}>Mark resolved</button>
          )}
        </article>
      ))}
    </section>
  );
}
