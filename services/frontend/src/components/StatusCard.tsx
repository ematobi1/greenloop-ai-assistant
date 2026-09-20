import type { HealthResult } from "../api/health";

const LABELS = {
  ok: { text: "Healthy", tone: "text-accent" },
  degraded: { text: "Degraded", tone: "text-warn" },
  unreachable: { text: "Backend unreachable", tone: "text-danger" },
} as const;

interface Props {
  result: HealthResult | null;
}

export default function StatusCard({ result }: Props) {
  const label = result ? LABELS[result.kind] : null;
  return (
    <section
      aria-labelledby="backend-status-heading"
      className="rounded-lg border border-line bg-panel p-5"
    >
      <h2 id="backend-status-heading" className="text-sm font-medium text-muted">
        Backend
      </h2>
      <p role="status" className={`mt-2 text-xl font-semibold ${label?.tone ?? "text-muted"}`}>
        {label ? label.text : "Checking..."}
      </p>
      {result && result.kind !== "unreachable" && (
        <dl className="mt-3 grid grid-cols-2 gap-1 text-sm text-muted">
          <dt>Database</dt>
          <dd>{result.health.database}</dd>
          <dt>Version</dt>
          <dd>{result.health.version}</dd>
        </dl>
      )}
      {result?.kind === "unreachable" && (
        <p className="mt-3 text-sm text-muted">
          Start the API with scripts\dev.ps1, then this card will update.
        </p>
      )}
    </section>
  );
}
