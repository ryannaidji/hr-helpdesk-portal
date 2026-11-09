import type {
  AuditEntry, ChatResponse, Escalation, LeaveBalance, LeaveRequest, LoginResponse, NewLeaveRequest,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiClient {
  constructor(private token: string | null = null, private fetchImpl: typeof fetch = (...a) => fetch(...a)) {}

  setToken(token: string | null) {
    this.token = token;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const response = await this.fetchImpl(path, { ...init, headers });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
    }
    return (await response.json()) as T;
  }

  private post<T>(path: string, body?: unknown) {
    return this.request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
  }

  login = (employee_id: string, password: string) => this.post<LoginResponse>("/api/auth/login", { employee_id, password });
  chat = (message: string) => this.post<ChatResponse>("/api/chat", { message });
  balance = (id: string) => this.request<LeaveBalance>(`/api/employees/${encodeURIComponent(id)}/leave-balance`);
  requests = (id: string) => this.request<LeaveRequest[]>(`/api/employees/${encodeURIComponent(id)}/leave-requests`);
  createRequest = (body: NewLeaveRequest) => this.post<LeaveRequest>("/api/leave-requests", body);
  approvals = () => this.request<LeaveRequest[]>("/api/approvals");
  decide = (id: number, decision: "approved" | "rejected") => this.post<LeaveRequest>(`/api/leave-requests/${id}/decision`, { decision });
  audit = () => this.request<AuditEntry[]>("/api/audit");
  escalations = () => this.request<Escalation[]>("/api/escalations");
  resolveEscalation = (id: number) => this.post<{ id: number; status: string }>(`/api/escalations/${id}/resolve`);
}
