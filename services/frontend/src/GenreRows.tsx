import { useEffect, useState } from "react";

import { genreLabel } from "./genres";
import { MovieRow } from "./MovieRow";
import { fetchRankings, type RankingsResult } from "./rankings";
import { isReady, useSystemStatus } from "./status";

/**
 * Lo mejor de cada género, arriba del catálogo. Solo en "ready": mientras se limpia o se
 * indexa no hay rankings, y el catálogo de abajo alcanza (consigna, punto 3).
 */
// Las primeras filas entran en una o dos pantallas; con las 22 juntas, el catálogo de abajo
// quedaba a varios miles de píxeles de scroll.
const FIRST_ROWS = 6;

export function GenreRows() {
  const { result: status, recheck } = useSystemStatus();
  const ready = isReady(status);
  const [attempt, setAttempt] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [result, setResult] = useState<RankingsResult>({ kind: "loading" });

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    setResult({ kind: "loading" });
    fetchRankings(controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      setResult(next);
      // Igual que las similares: el aviso de arriba vuelve a consultar el estado.
      if (next.kind === "failed" && (next.status === 409 || next.status === 503)) recheck();
    });
    return () => controller.abort();
  }, [ready, attempt, recheck]);

  if (!ready || result.kind === "loading") {
    return null; // sin "Cargando…": el catálogo de abajo ya se está mostrando
  }
  if (result.kind === "failed") {
    return (
      <p className="muted">
        No pudimos cargar lo mejor por género ({result.reason}) ·{" "}
        <button className="link" onClick={() => setAttempt((n) => n + 1)}>Reintentar</button>
      </p>
    );
  }
  const { rows } = result.data;
  const shown = showAll ? rows : rows.slice(0, FIRST_ROWS);
  return (
    <div className="genre-rows">
      {shown.map((row) => (
        <MovieRow
          key={row.genre}
          title={
            <>
              Lo mejor en <span className="accent">{genreLabel(row.genre)}</span>
            </>
          }
          movies={row.items}
        />
      ))}
      {rows.length > FIRST_ROWS && (
        <button className="more" onClick={() => setShowAll((all) => !all)}>
          {showAll ? "Ver menos géneros" : `Ver ${rows.length - FIRST_ROWS} géneros más`}
        </button>
      )}
    </div>
  );
}
