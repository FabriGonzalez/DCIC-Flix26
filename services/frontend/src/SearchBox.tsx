import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

// Espera desde la última tecla antes de buscar: así no sale un pedido por cada letra.
const SEARCH_DELAY_MS = 300;

/**
 * Buscador de la barra superior. La búsqueda vive en la URL del catálogo (/?q=…), así que
 * se puede usar desde cualquier pantalla: escribir en una ficha lleva al catálogo filtrado.
 */
export function SearchBox() {
  const navigate = useNavigate();
  const onCatalog = useLocation().pathname === "/";
  const [params] = useSearchParams();
  const query = onCatalog ? (params.get("q") ?? "") : "";
  const [text, setText] = useState(query);

  // Si la URL cambia desde afuera (atrás/adelante, abrir una ficha), el cuadro la acompaña.
  useEffect(() => setText(query), [query]);

  useEffect(() => {
    if (text === query) return; // sin esto, al entrar con ?page=3 se volvería a la página 1
    const timer = setTimeout(() => {
      const target = text ? `/?${new URLSearchParams({ q: text })}` : "/";
      // En el catálogo, replace: cada búsqueda no deja una entrada en el historial.
      // Desde una ficha, push: "atrás" vuelve a la ficha.
      navigate(target, { replace: onCatalog });
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, query, onCatalog, navigate]);

  return (
    <input
      className="search"
      type="search"
      placeholder="Buscar por título"
      aria-label="Buscar por título"
      value={text}
      onChange={(event) => setText(event.target.value)}
    />
  );
}
