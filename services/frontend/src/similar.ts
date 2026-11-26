// Películas similares según GET /api/movies/{id}/similar (README, "Recomendaciones").

import { getJson, type Fetched } from "./api";
import type { MovieCard } from "./movies";

export interface SimilarList {
  items: MovieCard[];
}

export type SimilarResult = { kind: "loading" } | Fetched<SimilarList>;

/** 409 = el sistema no está listo; 503 = el recomendador no responde. En los dos, hay que volver a consultar el estado. */
export function fetchSimilar(id: string, signal: AbortSignal): Promise<SimilarResult> {
  return getJson<SimilarList>(`/api/movies/${encodeURIComponent(id)}/similar`, signal);
}
