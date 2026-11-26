import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { NotFound } from "./NotFound";
import {
  fetchMovie,
  fetchReviews,
  withOwnVote,
  type MovieDetail,
  type MovieResult,
  type Review,
  type ReviewsResult,
  type ReviewsWithOwnVote,
  type ShownReview,
} from "./movie";
import { usePendingVotes } from "./pending";
import { Poster } from "./Poster";
import { useUser } from "./user";
import { VoteForm } from "./VoteForm";

const ratingFormat = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const countFormat = new Intl.NumberFormat("es-AR");
// timeZone UTC: las fechas vienen en UTC; en hora argentina, una de las 00:30 caería el día anterior.
const dayFormat = new Intl.DateTimeFormat("es-AR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

export function MovieDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<MovieResult>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setResult({ kind: "loading" });
    fetchMovie(id, controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      if (next.kind === "loaded" && next.data.id !== id) {
        // Copia duplicada fusionada en otra (A5): la URL pasa a ser la de la ganadora.
        // replace: "atrás" no vuelve a la copia. Cambiar el id repite el pedido, ya con el bueno.
        navigate(`/movies/${next.data.id}`, { replace: true });
        return;
      }
      setResult(next);
    });
    return () => controller.abort();
  }, [id, attempt, navigate]);

  if (result.kind === "loading") {
    return <p className="muted">Cargando…</p>;
  }
  if (result.kind === "failed") {
    if (result.status === 404) {
      return <NotFound message="No encontramos esta película." />;
    }
    return (
      <div className="banner error" role="alert">
        <strong>No pudimos cargar la película</strong>
        <p>
          {result.reason} · <button className="link" onClick={() => setAttempt((n) => n + 1)}>Reintentar</button>
        </p>
      </div>
    );
  }
  return <Detail movie={result.data} />;
}

/** Vuelve atrás en el historial (conserva búsqueda y página); con el link abierto directo, al catálogo. */
function BackLink() {
  const navigate = useNavigate();
  // "default" es la clave de la primera página que se abrió: no hay un "atrás" dentro de la app.
  const cameFromApp = useLocation().key !== "default";
  return (
    <Link
      to="/"
      className="back"
      onClick={(event) => {
        if (cameFromApp) {
          event.preventDefault();
          navigate(-1);
        }
      }}
    >
      ← Volver al catálogo
    </Link>
  );
}

function formatRuntime(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours === 0 ? `${rest} min` : rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

function Detail({ movie }: { movie: MovieDetail }) {
  const title = movie.title ?? "Sin título";
  const facts = [movie.year, movie.runtime !== null && formatRuntime(movie.runtime), movie.rated].filter(Boolean).join(" · ");
  const people: [string, string[]][] = [
    ["Dirección", movie.directors],
    ["Elenco", movie.cast],
    ["Países", movie.countries],
    ["Idiomas", movie.languages],
  ];
  return (
    <article className="detail">
      <BackLink />
      <div className="detail-main">
        <div className="detail-poster">
          <Poster url={movie.poster} title={title} />
        </div>
        <div>
          <h2>{title}</h2>
          {facts && <p className="muted">{facts}</p>}
          {movie.genres.length > 0 && <p className="muted">{movie.genres.join(", ")}</p>}
          {movie.imdbRating !== null && (
            <p>
              <strong>★ {ratingFormat.format(movie.imdbRating)}</strong>
              <span className="muted">
                {" "}en IMDb{movie.imdbVotes !== null && ` · ${countFormat.format(movie.imdbVotes)} votos`}
              </span>
            </p>
          )}
          <p className="plot">{movie.plot ?? <span className="muted">Sin sinopsis.</span>}</p>
          <dl className="facts">
            {people
              .filter(([, names]) => names.length > 0)
              .map(([label, names]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{names.join(", ")}</dd>
                </div>
              ))}
            {movie.awards && (
              <div>
                <dt>Premios</dt>
                <dd>{movie.awards}</dd>
              </div>
            )}
          </dl>
        </div>
      </div>
      {/* Con el id de la respuesta: si era una copia fusionada, las reseñas y los votos van a la ganadora. */}
      <VoteAndReviews movieId={movie.id} />
    </article>
  );
}

/**
 * "Tu voto" y las reseñas. Las reseñas se leen una vez para los dos: de ahí sale el voto
 * anterior del usuario, que precarga el formulario. Cambiar de usuario no vuelve a leer.
 */
function VoteAndReviews({ movieId }: { movieId: string }) {
  const { user } = useUser();
  const pendingVotes = usePendingVotes();
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<ReviewsResult>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setResult({ kind: "loading" });
    fetchReviews(movieId, controller.signal).then((next) => {
      if (!controller.signal.aborted) setResult(next);
    });
    return () => controller.abort();
  }, [movieId, attempt]);

  const pending = user === null ? null : pendingVotes.get(user.id, movieId);
  const shown = result.kind === "loaded" ? withOwnVote(result.data, user, pending) : null;

  // Si la lectura ya trae el voto enviado, la marca "Enviada" deja de hacer falta.
  const pendingSaved = shown?.pendingSaved ?? false;
  useEffect(() => {
    if (pending !== null && pendingSaved) pendingVotes.clear(pending);
  }, [pending, pendingSaved, pendingVotes]);

  // Lo último que votó: lo enviado si todavía no se leyó, si no, lo guardado.
  const own = shown?.own ?? null;
  const previous = pending ?? (own && { rating: own.rating, comment: own.comment ?? "" });

  return (
    <>
      <VoteForm movieId={movieId} previous={previous} loading={result.kind === "loading"} />
      <Reviews result={result} shown={shown} onRetry={() => setAttempt((n) => n + 1)} />
    </>
  );
}

function Reviews({
  result,
  shown,
  onRetry,
}: {
  result: ReviewsResult;
  shown: ReviewsWithOwnVote | null;
  onRetry: () => void;
}) {
  let body;
  if (result.kind === "loading") {
    body = <p className="muted">Cargando reseñas…</p>;
  } else if (result.kind === "failed") {
    body = (
      <p className="muted">
        No pudimos cargar las reseñas ({result.reason}) ·{" "}
        <button className="link" onClick={onRetry}>Reintentar</button>
      </p>
    );
  } else if (shown === null || shown.total === 0) {
    body = <p className="muted">Todavía no hay reseñas.</p>;
  } else {
    const { items, total } = shown;
    body = (
      <>
        <p className="muted">
          {total === 1 ? "1 reseña" : `${countFormat.format(total)} reseñas`}
          {items.length < total && ` · se muestran las ${items.length} más recientes`}
        </p>
        <ul className="reviews">
          {items.map((review) => (
            <li key={review.id}>
              <ReviewItem review={review} />
            </li>
          ))}
        </ul>
      </>
    );
  }
  return (
    <section className="reviews-section">
      <h3>Reseñas</h3>
      {body}
    </section>
  );
}

function formatDate(review: Review): string | null {
  if (review.date === null) return null;
  const date = new Date(review.date);
  // "circa 2023" se guardó como 1/1/2023: mostrar el día inventaría precisión.
  return review.datePrecision === "year" ? String(date.getUTCFullYear()) : dayFormat.format(date);
}

function ReviewItem({ review }: { review: ShownReview }) {
  const date = formatDate(review);
  return (
    <article className={review.own ? "review own" : "review"}>
      <header>
        <strong>
          {review.userName ?? "Usuario sin nombre"}
          {review.own && <span className="muted"> (vos)</span>}
        </strong>
        {review.rating !== null ? (
          <span className="stars" aria-label={`${review.rating} de 5 estrellas`}>
            {"★".repeat(review.rating)}
            {"☆".repeat(5 - review.rating)}
          </span>
        ) : (
          <span className="muted">Sin puntaje</span>
        )}
        {/* Enviada: aceptada, pero todavía no apareció en una lectura (S4). */}
        {review.sent ? <span className="tag">Enviada</span> : date && <span className="muted">{date}</span>}
      </header>
      {/* Sin comentario (oculto por basura, B7/B8): quedan el nombre, las estrellas y la fecha. */}
      {review.comment && <p>{review.comment}</p>}
    </article>
  );
}
