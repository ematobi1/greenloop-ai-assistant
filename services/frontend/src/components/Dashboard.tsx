import { useEffect, useState } from "react";
import { fetchHealth, type HealthResult } from "../api/health";
import StatusCard from "./StatusCard";

const POLL_INTERVAL_MS = 10_000;

const UPCOMING_CAPABILITIES = [
  "Conversations",
  "Voice",
  "Agents",
  "Memory",
  "Integrations",
  "Automation",
  "Security",
];

export default function Dashboard() {
  const [result, setResult] = useState<HealthResult | null>(null);

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

  return (
    <div className="min-h-screen">
      <header className="border-b border-line px-6 py-4">
        <h1 className="text-2xl font-semibold text-accent">GreenLoop</h1>
        <p className="text-sm text-muted">Personal AI assistant</p>
      </header>
      <main className="mx-auto grid max-w-5xl gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
        <StatusCard result={result} />
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
