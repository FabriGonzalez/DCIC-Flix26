import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { Card } from "./Card";
import { GenreRows } from "./GenreRows";
import { fetchMovies, type CatalogResult } from "./movies";

const countFormat = new Intl.NumberFormat("es-AR");

function parsePage(value: string | null): number {
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

export function Catalog() {
  // La búsqueda y la página viven en la URL (/?q=…&page=3): al volver de una ficha con
  // "atrás", el catálogo queda donde estaba, y el link se puede compartir. El cuadro de
  // búsqueda está en la barra superior (SearchBox).
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const page = parsePage(params.get("page"));

  const [attempt, setAttempt] = useState(0); // "Reintentar" lo incrementa para repetir el pedido
  const [result, setResult] = useState<CatalogResult>({ kind: "loading" });

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

  const goToPage = (next: number) => {
    setParams(query ? { q: query, page: String(next) } : { page: String(next) });
    window.scrollTo({ top: 0 }); // los botones están al pie: la página nueva se lee desde arriba
  };

  return (
    <section className="catalog">
      {/* Las filas solo en el catálogo "de entrada": al buscar o cambiar de página, estorban. */}
      {!query && page === 1 && <GenreRows />}
      <h2 className="section-title">{query.trim() ? `Resultados para "${query.trim()}"` : "Todo el catálogo"}</h2>
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
      {pages > 1 && (
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
      )}
    </>
  );
}
