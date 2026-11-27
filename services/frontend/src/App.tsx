import { Link, Route, Routes } from "react-router";

import { Catalog } from "./Catalog";
import { MovieDetailPage } from "./MovieDetail";
import { NotFound } from "./NotFound";
import { PendingVotesProvider } from "./pending";
import { StatusProvider, useSystemStatus, type SystemState } from "./status";
import { UserProvider } from "./user";
import { UserPicker } from "./UserPicker";

export function App() {
  return (
    // Arriba de todo: el estado y el usuario los leen el aviso, el encabezado y cada pantalla.
    <StatusProvider>
      <UserProvider>
        <PendingVotesProvider>
          <main className="page">
            <header className="top">
              <h1>
                <Link className="home" to="/">
                  DCIC-Flix
                </Link>
              </h1>
              <UserPicker />
            </header>
            {/* Fuera de Routes: el aviso se ve en todas las pantallas y no se reinicia al navegar. */}
            <StatusBanner />
            <Routes>
              <Route path="/" element={<Catalog />} />
              <Route path="/movies/:id" element={<MovieDetailPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </main>
        </PendingVotesProvider>
      </UserProvider>
    </StatusProvider>
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
