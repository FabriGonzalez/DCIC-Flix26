import { Catalog } from "./Catalog";
import { useSystemStatus, type SystemState } from "./status";

export function App() {
  return (
    <main className="page">
      <header>
        <h1>DCIC-Flix</h1>
      </header>
      <StatusBanner />
      <Catalog />
    </main>
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
  const status = useSystemStatus();
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
