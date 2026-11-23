// Catálogo según GET /api/movies (README, "Catálogo").

/** Una película como la manda el backend. Durante la limpieza, lo que no cumple el contrato llega en null. */
export interface MovieCard {
  id: string;
  title: string | null;
  year: number | null;
  poster: string | null;
  genres: string[];
  imdbRating: number | null;
}

export interface CatalogPage {
  items: MovieCard[];
  page: number;
  pageSize: number;
  total: number;
}

export type CatalogResult =
  | { kind: "loading" }
  | { kind: "loaded"; data: CatalogPage }
  | { kind: "failed"; reason: string };

const TIMEOUT_MS = 8000;

export async function fetchMovies(query: string, page: number, signal: AbortSignal): Promise<CatalogResult> {
  const params = new URLSearchParams({ page: String(page) });
  if (query.trim()) params.set("q", query.trim());
  try {
    const response = await fetch(`/api/movies?${params}`, {
      signal: AbortSignal.any([signal, AbortSignal.timeout(TIMEOUT_MS)]),
    });
    if (!response.ok) {
      return { kind: "failed", reason: `HTTP ${response.status}` };
    }
    return { kind: "loaded", data: (await response.json()) as CatalogPage };
  } catch (error) {
    const reason = error instanceof DOMException && error.name === "TimeoutError" ? "sin respuesta" : "error de red";
    return { kind: "failed", reason };
  }
}
