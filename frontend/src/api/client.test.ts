import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe("ApiClient", () => {
  it("sends the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, []));
    const api = new ApiClient("abc", fetchMock as typeof fetch);
    await api.approvals();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/approvals");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer abc");
  });

  it("omits the header when signed out", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, []));
    await new ApiClient(null, fetchMock as typeof fetch).audit();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it("surfaces the server denial message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(403, { detail: "Not authorized, or no such record." }));
    const error = await new ApiClient("t", fetchMock as typeof fetch).balance("E1006").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(403);
    expect(error.message).toContain("Not authorized");
  });

  it("copes with a non-JSON or structured error body", async () => {
    const text = vi.fn().mockResolvedValue(new Response("boom", { status: 500 }));
    await expect(new ApiClient("t", text as typeof fetch).audit()).rejects.toThrow("Request failed (500)");
    const structured = vi.fn().mockResolvedValue(json(422, { detail: [{ msg: "too long" }] }));
    await expect(new ApiClient("t", structured as typeof fetch).chat("x")).rejects.toThrow("Request failed (422)");
  });

  it("encodes path parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, {}));
    await new ApiClient("t", fetchMock as typeof fetch).balance("../audit");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/employees/..%2Faudit/leave-balance");
  });
});
