// Catálogo según GET /api/movies (README, "Catálogo").

import { getJson, type Fetched } from "./api";

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

export type CatalogResult = { kind: "loading" } | Fetched<CatalogPage>;

export function fetchMovies(query: string, page: number, signal: AbortSignal): Promise<CatalogResult> {
  const params = new URLSearchParams({ page: String(page) });
  if (query.trim()) params.set("q", query.trim());
  return getJson<CatalogPage>(`/api/movies?${params}`, signal);
}
