import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, jsonResponse, mockFetch } from "../test-utils";
import UnlockScreen from "./UnlockScreen";

afterEach(() => vi.unstubAllGlobals());

async function submitToken(value: string) {
  await userEvent.type(screen.getByLabelText("API token"), value);
  await userEvent.click(screen.getByRole("button", { name: "Unlock" }));
}

describe("UnlockScreen", () => {
  it("unlocks with a token the backend accepts", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ data: [], meta: { total: 0 } }));
    const onUnlock = vi.fn();
    render(<UnlockScreen onUnlock={onUnlock} />);

    await submitToken("good-token");

    await waitFor(() => expect(onUnlock).toHaveBeenCalledWith("good-token"));
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer good-token");
  });

  it("rejects a token the backend refuses", async () => {
    mockFetch(() => errorResponse(401, "UNAUTHENTICATED"));
    const onUnlock = vi.fn();
    render(<UnlockScreen onUnlock={onUnlock} />);

    await submitToken("bad-token");

    expect(await screen.findByRole("alert")).toHaveTextContent("not accepted");
    expect(onUnlock).not.toHaveBeenCalled();
  });

  it("reports an unreachable backend", async () => {
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    render(<UnlockScreen onUnlock={vi.fn()} />);

    await submitToken("any");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach");
  });

  it("masks the token field", () => {
    render(<UnlockScreen onUnlock={vi.fn()} />);
    expect(screen.getByLabelText("API token")).toHaveAttribute("type", "password");
  });
});
