// Estado del sistema según GET /api/status (README, "Estado del sistema").
//
// Lo consulta un solo lugar, StatusProvider, y lo lee cualquier componente con
// useSystemStatus(). Si cada uno consultara por su cuenta, habría el doble de pedidos y
// el aviso y el formulario de voto podrían mostrar estados distintos.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type SystemState = "cleaning" | "indexing" | "ready";

export type StatusResult =
  | { kind: "loading" }
  | { kind: "known"; state: SystemState }
  // 503 (el backend no pudo leer la marca), backend caído o sin red: no sabemos el estado.
  | { kind: "unknown"; reason: string };

export interface SystemStatus {
  result: StatusResult;
  /**
   * Vuelve a consultar hasta que el estado sea "ready". Lo llama quien recibe un 409:
   * con "ready" ya no se consulta, y el sistema pudo dejar de estar listo después.
   */
  recheck: () => void;
}

const POLL_MS = 3000;
const TIMEOUT_MS = 4000;

async function fetchStatus(): Promise<StatusResult> {
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

function sameResult(a: StatusResult, b: StatusResult): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

const StatusContext = createContext<SystemStatus | null>(null);

/** Consulta el estado cada POLL_MS hasta que es "ready"; después deja de consultar hasta un recheck(). */
export function StatusProvider({ children }: { children: ReactNode }) {
  const [result, setResult] = useState<StatusResult>({ kind: "loading" });
  const [round, setRound] = useState(0); // recheck() lo incrementa y la consulta vuelve a empezar

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // setTimeout encadenado y no setInterval: la próxima consulta se programa recién
    // cuando vuelve la anterior, así un backend lento no acumula pedidos.
    const poll = async () => {
      const next = await fetchStatus();
      if (!active) return;
      // Mismo estado, mismo objeto: así los que leen el contexto no se vuelven a dibujar cada 3 s.
      setResult((previous) => (sameResult(previous, next) ? previous : next));
      if (next.kind !== "known" || next.state !== "ready") {
        timer = setTimeout(poll, POLL_MS);
      }
    };
    poll();
    // Un recheck() mientras se consulta corta la ronda anterior: nunca hay dos a la vez.
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [round]);

  const recheck = useCallback(() => setRound((n) => n + 1), []);
  const value = useMemo(() => ({ result, recheck }), [result, recheck]);
  return <StatusContext value={value}>{children}</StatusContext>;
}

export function useSystemStatus(): SystemStatus {
  const status = useContext(StatusContext);
  if (status === null) {
    throw new Error("useSystemStatus fuera de StatusProvider");
  }
  return status;
}
