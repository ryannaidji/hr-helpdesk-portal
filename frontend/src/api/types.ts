export type Role = "employee" | "manager" | "hr";
export type Route = "policy" | "hr_action" | "escalate";
export type RequestStatus = "pending" | "approved" | "rejected";

export interface User {
  id: string;
  name: string;
  role: Role;
  manager_id: string | null;
  department: string;
}

export interface LoginResponse {
  token: string;
  user: User;
}

export interface ChatResponse {
  trace_id: string;
  route: Route;
  answer: string;
  citations: string[];
  escalation: { score: number; level: string; reasons: string[]; ticket_id: number | null };
  action: { tool: string; target: string | null; result: string; request_id?: number } | null;
  denied: boolean;
  abstained: boolean;
}

export interface LeaveBalance {
  employee_id: string;
  name: string;
  balances: Record<string, number>;
}

export interface LeaveRequest {
  id: number;
  employee_id: string;
  employee_name?: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  days: number;
  reason: string | null;
  status: RequestStatus;
  required_approver: "manager" | "hr";
}

export interface NewLeaveRequest {
  employee_id: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  reason: string;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  via_service: string | null;
  action: string;
  target: string | null;
  decision: string;
  reason: string;
}

export interface Escalation {
  id: number;
  employee_id: string;
  score: number;
  level: string;
  reasons: string[];
  message: string;
  status: "open" | "resolved";
  created_at: string;
}
