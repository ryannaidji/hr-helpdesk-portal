import { useState, type FormEvent } from "react";
import type { ApiClient } from "../api/client";
import type { User } from "../api/types";

const DEMO_USERS = [
  ["E1005", "Hana Sato (employee)"],
  ["E1003", "Amara Okafor (manager)"],
  ["E1002", "Tomasz Wilk (HR)"],
];

export function Login({ api, onLogin }: { api: ApiClient; onLogin: (user: User) => void }) {
  const [employeeId, setEmployeeId] = useState("E1005");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const { token, user } = await api.login(employeeId, password);
      api.setToken(token);
      onLogin(user);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <form className="card login" onSubmit={submit}>
      <h1>HR Helpdesk Portal</h1>
      <p className="tag">Demo over synthetic data. Halcyon Ridge Logistics and its staff are fictional.</p>
      <label>Demo user
        <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
          {DEMO_USERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <label>Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit">Sign in</button>
    </form>
  );
}
