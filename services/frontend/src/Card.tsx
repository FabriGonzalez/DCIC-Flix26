import { Link } from "react-router";

import type { MovieCard } from "./movies";
import { Poster } from "./Poster";

const ratingFormat = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** Tarjeta de una película: en el catálogo, en las filas por género y en las similares. */
export function Card({ movie }: { movie: MovieCard }) {
  const title = movie.title ?? "Sin título";
  // Lo que no se sabe (null) no se muestra; si no queda nada, no hay línea.
  const details = [movie.year, movie.imdbRating !== null && `★ ${ratingFormat.format(movie.imdbRating)}`]
    .filter(Boolean)
    .join(" · ");
  return (
    <Link className="movie" to={`/movies/${movie.id}`}>
      <Poster url={movie.poster} title={title} />
      <h2>{title}</h2>
      {details && <p className="muted">{details}</p>}
    </Link>
  );
}
