// Estado del sistema según GET /api/health del backend (D12).

export type DependencyStatus = "ok" | "error";

/** El JSON común de health del backend. */
export interface Health {
  service: string;
  status: DependencyStatus;
  dependencies: Record<string, DependencyStatus>;
  info: Record<string, DependencyStatus>;
  time?: string;
  detail?: string;
}

export type HealthResult =
  | { kind: "loading" }
  | { kind: "answered"; health: Health; checkedAt: Date } // 200 o 503: el backend respondió
  | { kind: "unavailable"; reason: string; checkedAt: Date }; // nginx no llegó al backend

const TIMEOUT_MS = 4000;

export async function fetchHealth(): Promise<HealthResult> {
  const checkedAt = new Date();
  try {
    const response = await fetch("/api/health", { signal: AbortSignal.timeout(TIMEOUT_MS) });
    // El backend responde JSON tanto con 200 como con 503. Si nginx no llega al
    // backend (caído o reiniciando), responde 502 o 504 con una página HTML.
    if (!response.headers.get("content-type")?.includes("application/json")) {
      return { kind: "unavailable", reason: `HTTP ${response.status}`, checkedAt };
    }
    return { kind: "answered", health: (await response.json()) as Health, checkedAt };
  } catch (error) {
    const reason = error instanceof DOMException && error.name === "TimeoutError" ? "sin respuesta" : "error de red";
    return { kind: "unavailable", reason, checkedAt };
  }
}
