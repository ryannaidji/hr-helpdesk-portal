import { useMemo, useState } from "react";
import { ApiClient } from "./api/client";
import type { Role, User } from "./api/types";
import { Approvals } from "./components/Approvals";
import { AuditLog } from "./components/AuditLog";
import { Chat } from "./components/Chat";
import { Escalations } from "./components/Escalations";
import { Login } from "./components/Login";
import { MyLeave } from "./components/MyLeave";

type Tab = "Assistant" | "My leave" | "Approvals" | "Escalations" | "Audit log";

/** Which tabs to show. This is convenience only: the server enforces every permission. */
export function tabsFor(role: Role): Tab[] {
  const tabs: Tab[] = ["Assistant", "My leave"];
  if (role !== "employee") tabs.push("Approvals");
  if (role === "hr") tabs.push("Escalations", "Audit log");
  return tabs;
}

export function App() {
  const api = useMemo(() => new ApiClient(), []);
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<Tab>("Assistant");

  if (!user) {
    return <Login api={api} onLogin={(u) => { setUser(u); setTab("Assistant"); }} />;
  }
  return (
    <div className="shell">
      <header>
        <strong>HR Helpdesk</strong>
        <span className="tag">Synthetic data: fictional company and people</span>
        <span className="spacer" />
        <span>{user.name} ({user.role})</span>
        <button onClick={() => { api.setToken(null); setUser(null); }}>Sign out</button>
      </header>
      <nav aria-label="Sections">
        {tabsFor(user.role).map((name) => (
          <button key={name} className={name === tab ? "active" : ""} aria-current={name === tab ? "page" : undefined} onClick={() => setTab(name)}>{name}</button>
        ))}
      </nav>
      <main>
        {tab === "Assistant" && <Chat api={api} />}
        {tab === "My leave" && <MyLeave api={api} user={user} />}
        {tab === "Approvals" && <Approvals api={api} />}
        {tab === "Escalations" && <Escalations api={api} />}
        {tab === "Audit log" && <AuditLog api={api} />}
      </main>
    </div>
  );
}
