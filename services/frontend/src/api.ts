// Pedidos GET al backend (en /api, por el proxy de nginx o de Vite).

export type Fetched<T> =
  | { kind: "loaded"; data: T }
  | { kind: "failed"; reason: string; status?: number };

const TIMEOUT_MS = 8000;

export async function getJson<T>(url: string, signal: AbortSignal): Promise<Fetched<T>> {
  try {
    const response = await fetch(url, { signal: AbortSignal.any([signal, AbortSignal.timeout(TIMEOUT_MS)]) });
    if (!response.ok) {
      return { kind: "failed", reason: `HTTP ${response.status}`, status: response.status };
    }
    return { kind: "loaded", data: (await response.json()) as T };
  } catch (error) {
    const reason = error instanceof DOMException && error.name === "TimeoutError" ? "sin respuesta" : "error de red";
    return { kind: "failed", reason };
  }
}
