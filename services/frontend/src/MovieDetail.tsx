import { useEffect, useState, type CSSProperties } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { genreLabel } from "./genres";
import { ChevronIcon } from "./icons";
import { MovieRow } from "./MovieRow";
import { NotFound } from "./NotFound";
import { fetchMovie, fetchReviews, type MovieDetail, type MovieResult, type Review, type ReviewsResult } from "./movie";
import { Poster } from "./Poster";
import { fetchSimilar, type SimilarResult } from "./similar";
import { isReady, useSystemStatus } from "./status";

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
      <ChevronIcon direction="left" />
      Volver
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
      <div className="detail-hero">
        {/* El póster, ampliado y difuminado, de fondo: le da a cada ficha el color de su película.
            Va en una variable de CSS porque la imagen la pinta un ::before (ver styles.css). */}
        {movie.poster && (
          <div
            className="detail-backdrop"
            style={{ "--backdrop": `url("${movie.poster}")` } as CSSProperties}
            aria-hidden="true"
          />
        )}
        <BackLink />
        <div className="detail-main">
          <div className="detail-poster">
            <Poster url={movie.poster} title={title} />
          </div>
          <div>
            <h1 className="detail-title">{title}</h1>
            {facts && <p className="muted">{facts}</p>}
            {movie.genres.length > 0 && (
              <ul className="chips">
                {movie.genres.map((genre) => (
                  <li key={genre}>{genreLabel(genre)}</li>
                ))}
              </ul>
            )}
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
        {/* Con el id de la respuesta: si era una copia fusionada, las reseñas están en la ganadora. */}
      </div>
      <Similar movieId={movie.id} />
      <Reviews movieId={movie.id} />
    </article>
  );
}

// Las reseñas que se ven de entrada; el resto, con "Ver todas". 16 tarjetas seguidas tapaban la ficha.
const FIRST_REVIEWS = 6;

function Reviews({ movieId }: { movieId: string }) {
  const [attempt, setAttempt] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [result, setResult] = useState<ReviewsResult>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setResult({ kind: "loading" });
    fetchReviews(movieId, controller.signal).then((next) => {
      if (!controller.signal.aborted) setResult(next);
    });
    return () => controller.abort();
  }, [movieId, attempt]);

  useEffect(() => setShowAll(false), [movieId]);

  let body;
  if (result.kind === "loading") {
    body = <p className="muted">Cargando reseñas…</p>;
  } else if (result.kind === "failed") {
    body = (
      <p className="muted">
        No pudimos cargar las reseñas ({result.reason}) ·{" "}
        <button className="link" onClick={() => setAttempt((n) => n + 1)}>Reintentar</button>
      </p>
    );
  } else if (result.data.total === 0) {
    body = <p className="muted">Todavía no hay reseñas.</p>;
  } else {
    const { items, total } = result.data;
    body = (
      <>
        <p className="muted">
          {total === 1 ? "1 reseña" : `${countFormat.format(total)} reseñas`}
          {items.length < total && ` · se muestran las ${items.length} más recientes`}
        </p>
        <ul className="reviews">
          {(showAll ? items : items.slice(0, FIRST_REVIEWS)).map((review) => (
            <li key={review.id}>
              <ReviewItem review={review} />
            </li>
          ))}
        </ul>
        {items.length > FIRST_REVIEWS && (
          <button className="more" onClick={() => setShowAll((all) => !all)}>
            {showAll ? "Ver menos reseñas" : `Ver las ${items.length} reseñas`}
          </button>
        )}
      </>
    );
  }
  return (
    <section className="detail-section">
      <h2 className="row-title">Reseñas</h2>
      {body}
    </section>
  );
}

/** Solo en "ready": mientras se limpia o indexa, las recomendaciones quedan en espera (consigna, punto 3). */
function Similar({ movieId }: { movieId: string }) {
  const { result: status, recheck } = useSystemStatus();
  const ready = isReady(status);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<SimilarResult>({ kind: "loading" });

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    setResult({ kind: "loading" });
    fetchSimilar(movieId, controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      setResult(next);
      // 409: dejó de estar listo después de "ready". 503: el recomendador no responde.
      // En los dos casos el aviso vuelve a consultar el estado.
      if (next.kind === "failed" && (next.status === 409 || next.status === 503)) recheck();
    });
    return () => controller.abort();
  }, [movieId, attempt, ready, recheck]);

  const title = "Películas similares";
  if (!ready || result.kind !== "loaded") {
    let message;
    if (!ready) message = "Disponibles cuando terminen de prepararse las recomendaciones.";
    else if (result.kind === "failed")
      message = (
        <>
          No pudimos cargar las películas similares ({result.reason}) ·{" "}
          <button className="link" onClick={() => setAttempt((n) => n + 1)}>Reintentar</button>
        </>
      );
    else message = "Cargando películas similares…";
    return (
      <section className="detail-section">
        <h2 className="row-title">{title}</h2>
        <p className="muted">{message}</p>
      </section>
    );
  }
  if (result.data.items.length === 0) {
    return null; // nada que mostrar: una sección vacía solo ocupa lugar
  }
  return (
    <div className="detail-section">
      <MovieRow title={title} movies={result.data.items} />
    </div>
  );
}

function formatDate(review: Review): string | null {
  if (review.date === null) return null;
  const date = new Date(review.date);
  // "circa 2023" se guardó como 1/1/2023: mostrar el día inventaría precisión.
  return review.datePrecision === "year" ? String(date.getUTCFullYear()) : dayFormat.format(date);
}

function ReviewItem({ review }: { review: Review }) {
  const date = formatDate(review);
  return (
    <article className="review">
      <header>
        <strong>{review.userName ?? "Usuario sin nombre"}</strong>
        {review.rating !== null ? (
          <span className="stars" aria-label={`${review.rating} de 5 estrellas`}>
            {"★".repeat(review.rating)}
            {"☆".repeat(5 - review.rating)}
          </span>
        ) : (
          <span className="muted">Sin puntaje</span>
        )}
        {date && <span className="muted">{date}</span>}
      </header>
      {/* Sin comentario (oculto por basura, B7/B8): quedan el nombre, las estrellas y la fecha. */}
      {review.comment && <p>{review.comment}</p>}
    </article>
  );
}
