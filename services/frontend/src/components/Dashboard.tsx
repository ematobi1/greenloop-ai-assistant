import { useCallback, useEffect, useState } from "react";
import { fetchHealth, type HealthResult } from "../api/health";
import { clearStoredToken, readStoredToken, storeToken } from "../auth/tokenStorage";
import ApprovalsPanel from "./ApprovalsPanel";
import ConversationList from "./ConversationList";
import StatusCard from "./StatusCard";
import UnlockScreen from "./UnlockScreen";

const POLL_INTERVAL_MS = 10_000;

const UPCOMING_CAPABILITIES = [
  "Chat",
  "Voice",
  "Agents",
  "Memory",
  "Integrations",
  "Automation",
  "Security",
];

export default function Dashboard() {
  const [result, setResult] = useState<HealthResult | null>(null);
  const [token, setToken] = useState<string | null>(readStoredToken);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => {
      fetchHealth(controller.signal)
        .then(setResult)
        .catch(() => undefined);
    };
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  const unlock = useCallback((value: string) => {
    storeToken(value);
    setToken(value);
  }, []);

  const lock = useCallback(() => {
    clearStoredToken();
    setToken(null);
  }, []);

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
          <h1 className="text-2xl font-semibold text-accent">GreenLoop</h1>
          <p className="text-sm text-muted">Personal AI assistant</p>
        </div>
        {token && (
          <button
            type="button"
            onClick={lock}
            className="rounded border border-line px-3 py-1 text-sm text-muted hover:text-danger"
          >
            Lock
          </button>
        )}
      </header>
      <main className="mx-auto grid max-w-5xl gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
        <StatusCard result={result} />
        {token ? (
          <>
            <ConversationList token={token} onUnauthorized={lock} />
            <ApprovalsPanel token={token} onUnauthorized={lock} />
          </>
        ) : (
          <UnlockScreen onUnlock={unlock} />
        )}
        {UPCOMING_CAPABILITIES.map((name) => (
          <section key={name} className="rounded-lg border border-line bg-panel p-5 opacity-60">
            <h2 className="text-sm font-medium text-muted">{name}</h2>
            <p className="mt-2 text-base text-muted">Not yet available</p>
          </section>
        ))}
      </main>
    </div>
  );
}
