import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, jsonResponse, mockFetch, noContent } from "../test-utils";
import ConversationList from "./ConversationList";

afterEach(() => vi.unstubAllGlobals());

const conversation = (id: string, title: string) => ({
  id,
  title,
  created_at: "2026-09-20T00:00:00Z",
  updated_at: "2026-09-20T00:00:00Z",
});

describe("ConversationList", () => {
  it("lists conversations", async () => {
    mockFetch(() =>
      jsonResponse({
        data: [conversation("1", "Trip"), conversation("2", "Resume")],
        meta: { total: 2 },
      }),
    );
    render(<ConversationList token="t" onUnauthorized={vi.fn()} />);

    expect(await screen.findByText("Trip")).toBeInTheDocument();
    expect(screen.getByText("Resume")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    mockFetch(() => jsonResponse({ data: [], meta: { total: 0 } }));
    render(<ConversationList token="t" onUnauthorized={vi.fn()} />);

    expect(await screen.findByText("No conversations yet.")).toBeInTheDocument();
  });

  it("creates a conversation and reloads the list", async () => {
    let items: ReturnType<typeof conversation>[] = [];
    const fetchMock = mockFetch((_url, init) => {
      if (init.method === "POST") {
        items = [conversation("9", JSON.parse(String(init.body)).title)];
        return jsonResponse(items[0], 201);
      }
      return jsonResponse({ data: items, meta: { total: items.length } });
    });
    render(<ConversationList token="t" onUnauthorized={vi.fn()} />);
    await screen.findByText("No conversations yet.");

    await userEvent.type(screen.getByLabelText("New conversation title"), "Groceries");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Groceries")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true);
  });

  it("deletes a conversation", async () => {
    let items = [conversation("1", "Trip")];
    mockFetch((_url, init) => {
      if (init.method === "DELETE") {
        items = [];
        return noContent();
      }
      return jsonResponse({ data: items, meta: { total: items.length } });
    });
    render(<ConversationList token="t" onUnauthorized={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Delete Trip" }));

    await waitFor(() => expect(screen.queryByText("Trip")).not.toBeInTheDocument());
  });

  it("locks when the token is rejected", async () => {
    mockFetch(() => errorResponse(401, "UNAUTHENTICATED"));
    const onUnauthorized = vi.fn();
    render(<ConversationList token="stale" onUnauthorized={onUnauthorized} />);

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalled());
  });
});
