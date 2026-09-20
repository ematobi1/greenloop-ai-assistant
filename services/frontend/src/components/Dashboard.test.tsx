import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../test-utils";
import Dashboard from "./Dashboard";

const HEALTH = { status: "ok", version: "0.2.0", database: "ok", time: "2026-09-19T00:00:00Z" };
const EMPTY_LIST = { data: [], meta: { total: 0 } };

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("Dashboard", () => {
  it("shows healthy backend", async () => {
    mockFetch(async () => json(HEALTH));
    render(<Dashboard />);
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("0.2.0")).toBeInTheDocument();
  });

  it("shows degraded backend on 503", async () => {
    mockFetch(async () => json({ ...HEALTH, status: "degraded", database: "error" }, 503));
    render(<Dashboard />);
    expect(await screen.findByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
  });

  it("shows unreachable backend when the request fails", async () => {
    mockFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    render(<Dashboard />);
    expect(await screen.findByText("Backend unreachable")).toBeInTheDocument();
  });

  it("marks later-phase capabilities as unavailable", async () => {
    mockFetch(async () => json(HEALTH));
    render(<Dashboard />);
    expect(screen.getAllByText("Not yet available")).toHaveLength(7);
    await screen.findByText("Healthy");
  });

  it("asks for a token when locked and loads no protected data", async () => {
    const fetchMock = mockFetch(async () => json(HEALTH));
    render(<Dashboard />);

    expect(screen.getByLabelText("API token")).toBeInTheDocument();
    await screen.findByText("Healthy");
    expect(fetchMock.mock.calls.every(([url]) => String(url) === "/v1/health")).toBe(true);
  });

  it("shows conversations and approvals with a stored token, and locks on demand", async () => {
    sessionStorage.setItem("greenloop.apiToken", "stored-token");
    mockFetch(async (url) => (url === "/v1/health" ? json(HEALTH) : json(EMPTY_LIST)));
    render(<Dashboard />);

    expect(await screen.findByText("No conversations yet.")).toBeInTheDocument();
    expect(await screen.findByText("No pending approvals.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Lock" }));

    expect(screen.getByLabelText("API token")).toBeInTheDocument();
    expect(sessionStorage.getItem("greenloop.apiToken")).toBeNull();
  });
});
