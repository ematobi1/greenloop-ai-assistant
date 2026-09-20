import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";

const HEALTH = { status: "ok", version: "0.1.0", database: "ok", time: "2026-09-19T00:00:00Z" };

function mockFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

afterEach(() => vi.unstubAllGlobals());

describe("Dashboard", () => {
  it("shows healthy backend", async () => {
    mockFetch(async () => new Response(JSON.stringify(HEALTH), { status: 200 }));
    render(<Dashboard />);
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
  });

  it("shows degraded backend on 503", async () => {
    const degraded = { ...HEALTH, status: "degraded", database: "error" };
    mockFetch(async () => new Response(JSON.stringify(degraded), { status: 503 }));
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
    mockFetch(async () => new Response(JSON.stringify(HEALTH), { status: 200 }));
    render(<Dashboard />);
    expect(screen.getAllByText("Not yet available")).toHaveLength(7);
    await screen.findByText("Healthy");
  });
});
