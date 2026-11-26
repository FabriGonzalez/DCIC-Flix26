// Votar según POST /api/movies/{id}/reviews (README, "Voto con reseña").

export const MAX_COMMENT_LENGTH = 5000; // el mismo tope que el backend (interactions.py)

/** Lo que aceptó el backend. Todavía no está guardado: lo guarda el ingest-consumer. */
export interface AcceptedVote {
  movieId: string;
  userId: string;
  rating: number;
  comment: string;
  votedAt: string; // ISO, en UTC, con milisegundos: la hora la pone el backend
}

export type VoteResult =
  | { kind: "accepted"; vote: AcceptedVote } // 202
  | { kind: "not-ready" } // 409: el estado no es "ready"
  | { kind: "rejected"; status: number; detail: string | null } // 404, 422, y lo inesperado
  | { kind: "unavailable" } // 503: Mongo o RabbitMQ no responden
  | { kind: "unknown"; reason: string }; // sin respuesta: no se sabe si llegó

// Comprobar y publicar tarda milisegundos, y la confirmación de RabbitMQ tiene un tope de
// 2 s (docs/ingest-consumer.md, V4). Más que eso es que algo no responde.
const TIMEOUT_MS = 8000;

export async function sendVote(movieId: string, userId: string, rating: number, comment: string): Promise<VoteResult> {
  let response: Response;
  try {
    response = await fetch(`/api/movies/${encodeURIComponent(movieId)}/reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId, rating, comment }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    const reason = error instanceof DOMException && error.name === "TimeoutError" ? "sin respuesta" : "error de red";
    return { kind: "unknown", reason };
  }
  if (response.status === 202) {
    return { kind: "accepted", vote: (await response.json()) as AcceptedVote };
  }
  if (response.status === 409) return { kind: "not-ready" };
  if (response.status === 503) return { kind: "unavailable" };
  return { kind: "rejected", status: response.status, detail: await readDetail(response) };
}

/**
 * El `detail` del backend, si es texto. Un JSON mal formado da `detail` como lista (FastAPI)
 * y un cuerpo demasiado grande, HTML de nginx: ahí conviene guiarse por el código.
 */
async function readDetail(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}
