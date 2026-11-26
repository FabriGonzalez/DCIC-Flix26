import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { Card } from "./Card";
import { GenreRows } from "./GenreRows";
import { fetchMovies, type CatalogResult } from "./movies";

// Espera desde la última tecla antes de buscar: así no sale un pedido por cada letra.
const SEARCH_DELAY_MS = 300;

const countFormat = new Intl.NumberFormat("es-AR");

function parsePage(value: string | null): number {
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

export function Catalog() {
  // La búsqueda y la página viven en la URL (/?q=…&page=3): al volver de una ficha con
  // "atrás", el catálogo queda donde estaba, y el link se puede compartir.
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const page = parsePage(params.get("page"));

  const [text, setText] = useState(query);
  const [attempt, setAttempt] = useState(0); // "Reintentar" lo incrementa para repetir el pedido
  const [result, setResult] = useState<CatalogResult>({ kind: "loading" });

  // Si la URL cambia desde afuera (atrás/adelante), el cuadro de búsqueda la acompaña.
  useEffect(() => setText(query), [query]);

  useEffect(() => {
    if (text === query) return; // sin esto, al entrar con ?page=3 se volvería a la página 1
    const timer = setTimeout(() => {
      // replace: cada búsqueda no deja una entrada en el historial; las páginas sí.
      setParams(text ? { q: text } : {}, { replace: true });
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, query, setParams]);

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

  const goToPage = (next: number) => setParams(query ? { q: query, page: String(next) } : { page: String(next) });

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
      {/* Las filas solo en el catálogo "de entrada": al buscar o cambiar de página, estorban. */}
      {!query && page === 1 && <GenreRows />}
      <Results result={result} query={query} onRetry={() => setAttempt((n) => n + 1)} onPage={goToPage} />
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
