import { useState, type FormEvent } from "react";
import { ApiError, request } from "../api/client";

interface Props {
  onUnlock: (token: string) => void;
}

export default function UnlockScreen({ onUnlock }: Props) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const token = value.trim();
    if (!token) return;
    setChecking(true);
    setError(null);
    try {
      await request("/v1/conversations?limit=1", token);
      onUnlock(token);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That token was not accepted."
          : "Could not reach the backend.",
      );
    } finally {
      setChecking(false);
    }
  }

  return (
    <section
      aria-labelledby="unlock-heading"
      className="rounded-lg border border-line bg-panel p-5 sm:col-span-2 lg:col-span-3"
    >
      <h2 id="unlock-heading" className="text-sm font-medium text-muted">
        Unlock
      </h2>
      <p className="mt-2 text-sm text-muted">
        Paste the API token printed by scripts\setup.ps1. Run scripts\new-token.ps1 for a new one.
      </p>
      <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="api-token" className="text-sm text-muted">
            API token
          </label>
          <input
            id="api-token"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            className="w-72 rounded border border-line bg-surface px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={checking}
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-surface disabled:opacity-60"
        >
          Unlock
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  );
}
