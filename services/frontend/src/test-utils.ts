import { vi } from "vitest";

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const noContent = () => new Response(null, { status: 204 });

export function errorResponse(status: number, code: string): Response {
  return jsonResponse({ error: { code, message: code } }, status);
}

export function mockFetch(
  handler: (url: string, init: RequestInit) => Response | Promise<Response>,
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) =>
    handler(String(input), init),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
