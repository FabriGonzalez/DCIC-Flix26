import { useState } from "react";

/** Carátula, o una genérica si no hay URL o la imagen no carga (≈12 % del dataset, A24). */
export function Poster({ url, title }: { url: string | null; title: string }) {
  const [broken, setBroken] = useState(false);
  if (!url || broken) {
    return (
      <div className="poster placeholder" aria-hidden="true">
        <span>{title}</span>
      </div>
    );
  }
  // alt vacío: el título ya está escrito al lado; repetirlo sería ruido para un lector de pantalla.
  return <img className="poster" src={url} alt="" loading="lazy" onError={() => setBroken(true)} />;
}
