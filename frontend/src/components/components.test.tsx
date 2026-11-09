import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api/client";
import type { ChatResponse, LeaveRequest } from "../api/types";
import { tabsFor } from "../App";
import { Approvals } from "./Approvals";
import { Chat } from "./Chat";
import { Login } from "./Login";

const reply = (over: Partial<ChatResponse>): ChatResponse => ({
  trace_id: "t1", route: "policy", answer: "Five days.", citations: [],
  escalation: { score: 0, level: "none", reasons: [], ticket_id: null },
  action: null, denied: false, abstained: false, ...over,
});

async function ask(api: Partial<ApiClient>) {
  render(<Chat api={api as ApiClient} />);
  await userEvent.type(screen.getByLabelText("Message"), "question");
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("tabsFor", () => {
  it("shows oversight tabs only to the right roles", () => {
    expect(tabsFor("employee")).toEqual(["Assistant", "My leave"]);
    expect(tabsFor("manager")).toContain("Approvals");
    expect(tabsFor("manager")).not.toContain("Audit log");
    expect(tabsFor("hr")).toContain("Audit log");
  });
});

describe("Chat", () => {
  it("renders citations", async () => {
    await ask({ chat: vi.fn().mockResolvedValue(reply({ citations: ["leave-policy#carryover"] })) });
    expect(await screen.findByText("leave-policy#carryover")).toBeInTheDocument();
    expect(screen.getByText("Policy agent")).toBeInTheDocument();
  });

  it("flags a denied request", async () => {
    await ask({ chat: vi.fn().mockResolvedValue(reply({ route: "hr_action", denied: true, answer: "Not authorized" })) });
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
  });

  it("shows an escalation and its score", async () => {
    const escalation = { score: 60, level: "high", reasons: ["harassment+60"], ticket_id: 3 };
    await ask({ chat: vi.fn().mockResolvedValue(reply({ route: "escalate", escalation })) });
    expect(await screen.findByText("Escalated to a person")).toBeInTheDocument();
    expect(screen.getByText(/score 60 \(high\)/)).toBeInTheDocument();
  });

  it("announces replies to assistive technology", async () => {
    await ask({ chat: vi.fn().mockResolvedValue(reply({})) });
    expect(screen.getByRole("log")).toHaveAttribute("aria-live", "polite");
    expect(await screen.findByText("Five days.")).toBeInTheDocument();
  });

  it("shows API errors", async () => {
    await ask({ chat: vi.fn().mockRejectedValue(new Error("offline")) });
    expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  });
});

describe("Login", () => {
  it("stores the token and reports the user", async () => {
    const user = { id: "E1005", name: "Hana", role: "employee", manager_id: "E1003", department: "Ops" };
    const api = { login: vi.fn().mockResolvedValue({ token: "tok", user }), setToken: vi.fn() };
    const onLogin = vi.fn();
    render(<Login api={api as unknown as ApiClient} onLogin={onLogin} />);
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(api.setToken).toHaveBeenCalledWith("tok");
    expect(onLogin).toHaveBeenCalledWith(user);
  });
});

describe("Approvals", () => {
  it("sends the decision and reloads", async () => {
    const row = { id: 7, employee_name: "Noah", leave_type: "annual", start_date: "2031-03-03", end_date: "2031-03-05", days: 3 } as LeaveRequest;
    const api = { approvals: vi.fn().mockResolvedValue([row]), decide: vi.fn().mockResolvedValue(row) };
    render(<Approvals api={api as unknown as ApiClient} />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(api.decide).toHaveBeenCalledWith(7, "approved");
    expect(api.approvals).toHaveBeenCalledTimes(2);
  });
});
