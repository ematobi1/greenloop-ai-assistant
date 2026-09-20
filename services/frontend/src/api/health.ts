export interface Health {
  status: "ok" | "degraded";
  version: string;
  database: "ok" | "error";
  time: string;
}

export type HealthResult =
  | { kind: "ok"; health: Health }
  | { kind: "degraded"; health: Health }
  | { kind: "unreachable" };

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResult> {
  try {
    const response = await fetch("/v1/health", { signal });
    const health = (await response.json()) as Health;
    return { kind: health.status === "ok" ? "ok" : "degraded", health };
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    return { kind: "unreachable" };
  }
}
