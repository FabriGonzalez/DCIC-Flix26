// Ficha según GET /api/movies/{id} y /api/movies/{id}/reviews (README, "Ficha").

import { getJson, type Fetched } from "./api";
import type { MovieCard } from "./movies";

export interface MovieDetail extends MovieCard {
  plot: string | null;
  runtime: number | null; // minutos
  rated: string | null;
  directors: string[];
  cast: string[];
  countries: string[];
  languages: string[];
  imdbVotes: number | null;
  awards: string | null;
}

/** null = no se sabe. Una reseña activa se muestra aunque le falten las estrellas o el texto. */
export interface Review {
  id: string;
  userName: string | null;
  rating: number | null;
  comment: string | null;
  date: string | null; // ISO, en UTC
  datePrecision: "day" | "year" | null;
}

export interface ReviewsPage {
  items: Review[];
  total: number;
}

export type MovieResult = { kind: "loading" } | Fetched<MovieDetail>;
export type ReviewsResult = { kind: "loading" } | Fetched<ReviewsPage>;

export function fetchMovie(id: string, signal: AbortSignal): Promise<MovieResult> {
  return getJson<MovieDetail>(`/api/movies/${encodeURIComponent(id)}`, signal);
}

export function fetchReviews(id: string, signal: AbortSignal): Promise<ReviewsResult> {
  return getJson<ReviewsPage>(`/api/movies/${encodeURIComponent(id)}/reviews`, signal);
}
