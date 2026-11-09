import { useState, type FormEvent } from "react";
import type { ApiClient } from "../api/client";
import type { ChatResponse } from "../api/types";

type Turn = { question: string; reply: ChatResponse };

const ROUTE_LABEL = { policy: "Policy agent", hr_action: "HR action agent", escalate: "Escalated to a person" };

export function Chat({ api }: { api: ApiClient }) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!message.trim()) return;
    setBusy(true);
    setError("");
    try {
      const reply = await api.chat(message);
      setTurns((previous) => [...previous, { question: message, reply }]);
      setMessage("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Ask HR</h2>
      <div role="log" aria-live="polite" aria-label="Conversation">
      {turns.map(({ question, reply }) => (
        <article className="card" key={reply.trace_id}>
          <p className="question">{question}</p>
          <p>{reply.answer}</p>
          <p className="meta">
            <span className={`badge ${reply.route}`}>{ROUTE_LABEL[reply.route]}</span>
            {reply.denied && <span className="badge denied">Access denied</span>}
            <span>Escalation score {reply.escalation.score} ({reply.escalation.level})</span>
          </p>
          {reply.citations.length > 0 && (
            <ul aria-label="Sources">{reply.citations.map((c) => <li key={c}><code>{c}</code></li>)}</ul>
          )}
        </article>
      ))}
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      <form className="row" onSubmit={send}>
        <input aria-label="Message" value={message} maxLength={2000} placeholder="Ask about a policy or your leave"
          onChange={(e) => setMessage(e.target.value)} />
        <button disabled={busy}>{busy ? "Working..." : "Send"}</button>
      </form>
    </section>
  );
}
