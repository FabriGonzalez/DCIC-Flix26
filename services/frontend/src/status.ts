// Estado del sistema según GET /api/status (README, "Estado del sistema").

import { createContext, useCallback, useContext, useEffect, useState } from "react";

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

export interface SystemStatus {
  result: StatusResult;
  /** Vuelve a consultar hasta "ready": cuando una acción falla por el estado (README, "Estado del sistema"). */
  recheck: () => void;
}

/** Consulta el estado cada POLL_MS hasta que es "ready"; después deja de consultar, hasta un recheck(). */
export function useStatusPolling(): SystemStatus {
  const [result, setResult] = useState<StatusResult>({ kind: "loading" });
  const [round, setRound] = useState(0);

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
  }, [round]);

  const recheck = useCallback(() => setRound((n) => n + 1), []);
  return { result, recheck };
}

// Una sola consulta para toda la app: la provee App y la leen el aviso y las pantallas.
export const StatusContext = createContext<SystemStatus | null>(null);

export function useSystemStatus(): SystemStatus {
  const status = useContext(StatusContext);
  if (status === null) throw new Error("useSystemStatus fuera de StatusContext");
  return status;
}

export function isReady(result: StatusResult): boolean {
  return result.kind === "known" && result.state === "ready";
}
