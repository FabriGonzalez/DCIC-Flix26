import { useEffect, useRef, useState, type ReactNode } from "react";

import { Card } from "./Card";
import type { MovieCard } from "./movies";

/**
 * Fila de tarjetas que se desplaza de costado (filas por género, similares). Las flechas
 * aparecen solo si hay algo más para ese lado; en pantallas táctiles se desliza con el dedo.
 */
export function MovieRow({ title, movies }: { title: ReactNode; movies: MovieCard[] }) {
  const scroller = useRef<HTMLUListElement>(null);
  const [edges, setEdges] = useState({ start: true, end: true });

  const updateEdges = () => {
    const el = scroller.current;
    if (!el) return;
    // 2 px de margen: con zoom, scrollLeft puede quedar en un decimal y nunca llegar justo al final.
    setEdges({ start: el.scrollLeft <= 2, end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 2 });
  };

  useEffect(() => {
    updateEdges();
    window.addEventListener("resize", updateEdges);
    return () => window.removeEventListener("resize", updateEdges);
  }, [movies]);

  const move = (direction: 1 | -1) => {
    const el = scroller.current;
    if (el) el.scrollBy({ left: direction * el.clientWidth * 0.9, behavior: "smooth" });
  };

  return (
    <section className="movie-row">
      <h2 className="row-title">{title}</h2>
      <div className="row-frame">
        {!edges.start && (
          <button className="row-arrow prev" aria-label="Anteriores" onClick={() => move(-1)}>
            ‹
          </button>
        )}
        <ul className="row-scroll" ref={scroller} onScroll={updateEdges}>
          {movies.map((movie) => (
            <li key={movie.id}>
              <Card movie={movie} />
            </li>
          ))}
        </ul>
        {!edges.end && (
          <button className="row-arrow next" aria-label="Siguientes" onClick={() => move(1)}>
            ›
          </button>
        )}
      </div>
    </section>
  );
}
