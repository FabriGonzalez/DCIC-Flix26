import { useEffect, useState } from "react";

import { fetchMovies, type CatalogResult, type MovieCard } from "./movies";

// Espera desde la última tecla antes de buscar: así no sale un pedido por cada letra.
const SEARCH_DELAY_MS = 300;

const ratingFormat = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const countFormat = new Intl.NumberFormat("es-AR");

export function Catalog() {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0); // "Reintentar" lo incrementa para repetir el pedido
  const [result, setResult] = useState<CatalogResult>({ kind: "loading" });

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(text);
      setPage(1);
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    // Si cambian la búsqueda o la página antes de que vuelva el pedido, se cancela: si no,
    // una respuesta vieja que llega tarde podría pisar a la nueva.
    const controller = new AbortController();
    setResult({ kind: "loading" });
    fetchMovies(query, page, controller.signal).then((next) => {
      if (!controller.signal.aborted) setResult(next);
    });
    return () => controller.abort();
  }, [query, page, attempt]);

  return (
    <section className="catalog">
      <input
        className="search"
        type="search"
        placeholder="Buscar por título"
        aria-label="Buscar por título"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <Results result={result} query={query} onRetry={() => setAttempt((n) => n + 1)} onPage={setPage} />
    </section>
  );
}

function Results({
  result,
  query,
  onRetry,
  onPage,
}: {
  result: CatalogResult;
  query: string;
  onRetry: () => void;
  onPage: (page: number) => void;
}) {
  if (result.kind === "loading") {
    return <p className="muted">Cargando…</p>;
  }
  if (result.kind === "failed") {
    return (
      <div className="banner error" role="alert">
        <strong>No pudimos cargar el catálogo</strong>
        <p>
          {result.reason} · <button className="link" onClick={onRetry}>Reintentar</button>
        </p>
      </div>
    );
  }
  const { items, page, pageSize, total } = result.data;
  if (total === 0) {
    return <p className="muted">{query.trim() ? `No hay películas que coincidan con "${query.trim()}".` : "El catálogo está vacío."}</p>;
  }
  const pages = Math.ceil(total / pageSize);
  return (
    <>
      <p className="muted">{countFormat.format(total)} películas</p>
      <ul className="grid">
        {items.map((movie) => (
          <li key={movie.id}>
            <Card movie={movie} />
          </li>
        ))}
      </ul>
      <nav className="pager" aria-label="Páginas">
        <button disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Anterior
        </button>
        <span>
          Página {page} de {pages}
        </span>
        <button disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Siguiente
        </button>
      </nav>
    </>
  );
}

function Card({ movie }: { movie: MovieCard }) {
  const title = movie.title ?? "Sin título";
  // Lo que no se sabe (null) no se muestra; si no queda nada, no hay línea.
  const details = [movie.year, movie.imdbRating !== null && `★ ${ratingFormat.format(movie.imdbRating)}`]
    .filter(Boolean)
    .join(" · ");
  return (
    <article className="movie">
      <Poster url={movie.poster} title={title} />
      <h2>{title}</h2>
      {details && <p className="muted">{details}</p>}
    </article>
  );
}

/** Carátula, o una genérica si no hay URL o la imagen no carga (≈12 % del dataset, A24). */
function Poster({ url, title }: { url: string | null; title: string }) {
  const [broken, setBroken] = useState(false);
  if (!url || broken) {
    return (
      <div className="poster placeholder" aria-hidden="true">
        <span>{title}</span>
      </div>
    );
  }
  // alt vacío: el título ya está escrito debajo; repetirlo sería ruido para un lector de pantalla.
  return <img className="poster" src={url} alt="" loading="lazy" onError={() => setBroken(true)} />;
}
