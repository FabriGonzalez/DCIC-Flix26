import { useEffect, useState } from "react";

import { Card } from "./Card";
import { fetchRankings, type RankingsResult } from "./rankings";
import { isReady, useSystemStatus } from "./status";

/**
 * Lo mejor de cada género, arriba del catálogo. Solo en "ready": mientras se limpia o se
 * indexa no hay rankings, y el catálogo de abajo alcanza (consigna, punto 3).
 */
export function GenreRows() {
  const { result: status, recheck } = useSystemStatus();
  const ready = isReady(status);
  const [attempt, setAttempt] = useState(0);
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
  return (
    <div className="genre-rows">
      {result.data.rows.map((row) => (
        <section key={row.genre} className="genre-row">
          <h2>{row.genre}</h2>
          <ul className="row-scroll">
            {row.items.map((movie) => (
              <li key={movie.id}>
                <Card movie={movie} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
