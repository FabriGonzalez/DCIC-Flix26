import { useEffect, useState } from "react";

import { fetchHealth, type DependencyStatus, type HealthResult } from "./health";

const POLL_MS = 5000;

const LABELS: Record<string, string> = {
  mongodb: "MongoDB",
  rabbitmq: "RabbitMQ",
  topology: "Topología de RabbitMQ",
  recommender: "Recomendador",
};

export function App() {
  const [result, setResult] = useState<HealthResult>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    const poll = async () => {
      const next = await fetchHealth();
      if (active) setResult(next);
    };
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <main className="page">
      <header>
        <h1>DCIC-Flix</h1>
        <p className="subtitle">Estado del sistema</p>
      </header>
      <StatusCard result={result} />
    </main>
  );
}

function StatusCard({ result }: { result: HealthResult }) {
  if (result.kind === "loading") {
    return <section className="card">Consultando…</section>;
  }
  if (result.kind === "unavailable") {
    return (
      <section className="card">
        <Summary tone="down" title="Backend no disponible" detail={result.reason} />
        <Footer checkedAt={result.checkedAt} />
      </section>
    );
  }
  const { health } = result;
  const ok = health.status === "ok";
  return (
    <section className="card">
      <Summary
        tone={ok ? "ok" : "error"}
        title={ok ? "Funcionando" : "Con problemas"}
        detail={health.detail}
      />
      <DependencyList title="Dependencias" items={health.dependencies} />
      {Object.keys(health.info).length > 0 && (
        <DependencyList title="Informativas (no afectan el estado)" items={health.info} />
      )}
      <Footer checkedAt={result.checkedAt} />
    </section>
  );
}

function Summary({ tone, title, detail }: { tone: "ok" | "error" | "down"; title: string; detail?: string }) {
  return (
    <div className={`summary ${tone}`}>
      <span className="dot" aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        {detail && <p className="detail">{detail}</p>}
      </div>
    </div>
  );
}

function DependencyList({ title, items }: { title: string; items: Record<string, DependencyStatus> }) {
  return (
    <div className="deps">
      <h2>{title}</h2>
      <ul>
        {Object.entries(items).map(([name, status]) => (
          <li key={name}>
            <span>{LABELS[name] ?? name}</span>
            <span className={`badge ${status}`}>{status === "ok" ? "ok" : "error"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Footer({ checkedAt }: { checkedAt: Date }) {
  return (
    <p className="footer">
      Última consulta: {checkedAt.toLocaleTimeString("es-AR")} · se actualiza cada {POLL_MS / 1000} s
    </p>
  );
}
