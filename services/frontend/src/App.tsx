import { Link, Route, Routes } from "react-router";

import { Catalog } from "./Catalog";
import { MovieDetailPage } from "./MovieDetail";
import { NotFound } from "./NotFound";
import { SearchBox } from "./SearchBox";
import { StatusContext, useStatusPolling, useSystemStatus, type SystemState } from "./status";

export function App() {
  return (
    <StatusContext.Provider value={useStatusPolling()}>
      <Layout />
    </StatusContext.Provider>
  );
}

function Layout() {
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="brand" to="/" aria-label="DCIC-Flix, ir al inicio">
            DCIC<span>Flix</span>
          </Link>
          <SearchBox />
          {/* Lugar del menú de usuario (selector, arriba a la derecha). */}
          <div className="topbar-user" />
        </div>
      </header>
      <main className="page">
        {/* Fuera de Routes: el aviso se ve en todas las pantallas y no se reinicia al navegar. */}
        <StatusBanner />
        <Routes>
          <Route path="/" element={<Catalog />} />
          <Route path="/movies/:id" element={<MovieDetailPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  );
}

const BANNERS: Record<Exclude<SystemState, "ready">, { title: string; detail: string }> = {
  cleaning: {
    title: "Estamos limpiando los datos",
    detail: "Podés recorrer el catálogo. Las recomendaciones y los votos se habilitan al terminar.",
  },
  indexing: {
    title: "Preparando las recomendaciones",
    detail: "Los datos ya están limpios. Las recomendaciones y los votos se habilitan en unos minutos.",
  },
};

function StatusBanner() {
  const status = useSystemStatus().result;
  if (status.kind === "loading") {
    return null;
  }
  if (status.kind === "unknown") {
    return (
      <div className="banner error" role="status">
        <strong>No pudimos consultar el estado del sistema</strong>
        <p>Reintentando… ({status.reason})</p>
      </div>
    );
  }
  if (status.state === "ready") {
    return null;
  }
  const { title, detail } = BANNERS[status.state];
  return (
    <div className="banner" role="status">
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}
