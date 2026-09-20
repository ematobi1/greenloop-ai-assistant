import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, jsonResponse, mockFetch } from "../test-utils";
import ApprovalsPanel from "./ApprovalsPanel";

afterEach(() => vi.unstubAllGlobals());

const approval = (id: string, action: string, status = "pending") => ({
  id,
  action,
  description: "Reply to recruiter",
  status,
  decided_at: null,
  created_at: "2026-09-20T00:00:00Z",
  updated_at: "2026-09-20T00:00:00Z",
});

describe("ApprovalsPanel", () => {
  it("lists pending approvals", async () => {
    mockFetch(() => jsonResponse({ data: [approval("1", "send_email")], meta: { total: 1 } }));
    render(<ApprovalsPanel token="t" onUnauthorized={vi.fn()} />);

    expect(await screen.findByText("send_email")).toBeInTheDocument();
    expect(screen.getByText("Reply to recruiter")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    mockFetch(() => jsonResponse({ data: [], meta: { total: 0 } }));
    render(<ApprovalsPanel token="t" onUnauthorized={vi.fn()} />);

    expect(await screen.findByText("No pending approvals.")).toBeInTheDocument();
  });

  it("sends the decision and removes the item", async () => {
    let pending = [approval("1", "send_email")];
    const fetchMock = mockFetch((url, init) => {
      if (init.method === "POST") {
        pending = [];
        return jsonResponse(approval("1", "send_email", "approved"));
      }
      expect(url).toContain("status=pending");
      return jsonResponse({ data: pending, meta: { total: pending.length } });
    });
    render(<ApprovalsPanel token="t" onUnauthorized={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Approve send_email" }));

    await waitFor(() => expect(screen.queryByText("send_email")).not.toBeInTheDocument());
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(String(post[0])).toBe("/v1/approvals/1/decision");
    expect(JSON.parse(String(post[1]?.body))).toEqual({ decision: "approved" });
  });

  it("sends denials", async () => {
    const fetchMock = mockFetch((_url, init) =>
      init.method === "POST"
        ? jsonResponse(approval("1", "send_email", "denied"))
        : jsonResponse({ data: [approval("1", "send_email")], meta: { total: 1 } }),
    );
    render(<ApprovalsPanel token="t" onUnauthorized={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Deny send_email" }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
      expect(JSON.parse(String(post[1]?.body))).toEqual({ decision: "denied" });
    });
  });

  it("treats an already-decided approval as resolved and refreshes", async () => {
    let pending = [approval("1", "send_email")];
    mockFetch((_url, init) => {
      if (init.method === "POST") {
        pending = [];
        return errorResponse(409, "APPROVAL_ALREADY_DECIDED");
      }
      return jsonResponse({ data: pending, meta: { total: pending.length } });
    });
    render(<ApprovalsPanel token="t" onUnauthorized={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Approve send_email" }));

    await waitFor(() => expect(screen.queryByText("send_email")).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("locks when the token is rejected", async () => {
    mockFetch(() => errorResponse(401, "UNAUTHENTICATED"));
    const onUnauthorized = vi.fn();
    render(<ApprovalsPanel token="stale" onUnauthorized={onUnauthorized} />);

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalled());
  });
});
