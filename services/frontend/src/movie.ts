// Ficha según GET /api/movies/{id} y /api/movies/{id}/reviews (README, "Ficha").

import { getJson, type Fetched } from "./api";
import type { MovieCard } from "./movies";
import type { User } from "./users";
import type { AcceptedVote } from "./votes";

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
  userId: string | null; // para reconocer la reseña propia: los nombres se repiten
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

export interface ShownReview extends Review {
  own: boolean; // del usuario elegido
  sent: boolean; // enviada y todavía no leída: se muestra el voto que aceptó el backend
}

export interface ReviewsWithOwnVote {
  items: ShownReview[];
  total: number;
  own: Review | null; // la reseña propia según la lectura, si la hay
  /** La lectura ya trae el voto enviado (o uno más nuevo): deja de hacer falta. */
  pendingSaved: boolean;
}

/**
 * Las reseñas leídas, con la propia marcada y el voto enviado en su lugar si la lectura todavía
 * no lo trae. Se compara por fecha: el backend pone votedAt y el consumer la guarda tal cual.
 */
export function withOwnVote(page: ReviewsPage, user: User | null, pending: AcceptedVote | null): ReviewsWithOwnVote {
  const isOwn = (review: Review) => user !== null && review.userId === user.id;
  const own = page.items.find(isOwn) ?? null;
  const pendingSaved =
    pending !== null && own !== null && own.date !== null && Date.parse(own.date) >= Date.parse(pending.votedAt);

  let items: ShownReview[] = page.items.map((review) => ({ ...review, own: isOwn(review), sent: false }));
  let total = page.total;
  if (user !== null && pending !== null && !pendingSaved) {
    const sent: ShownReview = {
      id: `enviada-${pending.votedAt}`,
      userId: user.id,
      userName: user.name,
      rating: pending.rating,
      // Como lo guarda el consumer: un comentario vacío queda oculto.
      comment: pending.comment.trim() || null,
      date: pending.votedAt,
      datePrecision: "day",
      own: true,
      sent: true,
    };
    // Primero, porque es la más reciente. Reemplaza al voto anterior, que deja de valer.
    items = [sent, ...items.filter((review) => !review.own)];
    if (own === null) total += 1;
  }
  return { items, total, own, pendingSaved };
}
