// Filas por género según GET /api/rankings (README, "Recomendaciones").

import { getJson, type Fetched } from "./api";
import type { MovieCard } from "./movies";

export interface GenreRow {
  genre: string;
  items: MovieCard[];
}

export type RankingsResult = { kind: "loading" } | Fetched<{ rows: GenreRow[] }>;

/** 409 = el sistema no está listo; 503 = el recomendador no responde. En los dos, hay que volver a consultar el estado. */
export function fetchRankings(signal: AbortSignal): Promise<RankingsResult> {
  return getJson<{ rows: GenreRow[] }>("/api/rankings", signal);
}
