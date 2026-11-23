// Estado del sistema según GET /api/status (README, "Estado del sistema").

import { useEffect, useState } from "react";

export type SystemState = "cleaning" | "indexing" | "ready";

export type StatusResult =
  | { kind: "loading" }
  | { kind: "known"; state: SystemState }
  // 503 (el backend no pudo leer la marca), backend caído o sin red: no sabemos el estado.
  | { kind: "unknown"; reason: string };

const POLL_MS = 3000;
const TIMEOUT_MS = 4000;

export async function fetchStatus(): Promise<StatusResult> {
  try {
    const response = await fetch("/api/status", { signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!response.ok) {
      return { kind: "unknown", reason: `HTTP ${response.status}` };
    }
    const body = (await response.json()) as { state: SystemState };
    return { kind: "known", state: body.state };
  } catch (error) {
    const reason = error instanceof DOMException && error.name === "TimeoutError" ? "sin respuesta" : "error de red";
    return { kind: "unknown", reason };
  }
}

/** Consulta el estado cada POLL_MS hasta que es "ready"; después deja de consultar. */
export function useSystemStatus(): StatusResult {
  const [result, setResult] = useState<StatusResult>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // setTimeout encadenado y no setInterval: la próxima consulta se programa recién
    // cuando vuelve la anterior, así un backend lento no acumula pedidos.
    const poll = async () => {
      const next = await fetchStatus();
      if (!active) return;
      setResult(next);
      if (next.kind !== "known" || next.state !== "ready") {
        timer = setTimeout(poll, POLL_MS);
      }
    };
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);

  return result;
}
