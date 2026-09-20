import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, jsonResponse, mockFetch, noContent } from "../test-utils";
import { ApiError, request } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
  it("sends the bearer token and JSON content type", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));

    await request("/v1/x", "secret", { method: "POST", body: "{}" });

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer secret");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("returns undefined for 204", async () => {
    mockFetch(noContent);
    await expect(request("/v1/x", "t", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("throws ApiError carrying status and code", async () => {
    mockFetch(() => errorResponse(409, "APPROVAL_ALREADY_DECIDED"));
    await expect(request("/v1/x", "t")).rejects.toMatchObject({
      status: 409,
      code: "APPROVAL_ALREADY_DECIDED",
    });
    await expect(request("/v1/x", "t")).rejects.toBeInstanceOf(ApiError);
  });

  it("survives a non-JSON error body", async () => {
    mockFetch(() => new Response("oops", { status: 502 }));
    await expect(request("/v1/x", "t")).rejects.toMatchObject({ status: 502, code: "UNKNOWN" });
  });
});
