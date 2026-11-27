import { useEffect, useRef, useState } from "react";

import { useUser } from "./user";
import { fetchUsers, type User, type UsersResult } from "./users";

// Igual que el catálogo: espera desde la última tecla, para no pedir por cada letra.
const SEARCH_DELAY_MS = 300;

const countFormat = new Intl.NumberFormat("es-AR");

/** Botón del encabezado: muestra el usuario elegido y abre la lista para cambiarlo (también desde otras pantallas, con openPicker). */
export function UserPicker() {
  const { user, choose, pickerOpen, openPicker, closePicker } = useUser();
  return (
    <>
      <button className="user-button" aria-haspopup="dialog" onClick={openPicker}>
        {user ? (
          <>
            {user.name} <span className="muted">· {user.id}</span>
          </>
        ) : (
          "Elegir usuario"
        )}
      </button>
      {/* Montado solo mientras está abierto: cada vez arranca con la búsqueda vacía. */}
      {pickerOpen && <UserDialog current={user} onChoose={choose} onClose={closePicker} />}
    </>
  );
}

function UserDialog({
  current,
  onChoose,
  onClose,
}: {
  current: User | null;
  onChoose: (user: User | null) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [attempt, setAttempt] = useState(0);
  // La respuesta y la búsqueda a la que corresponde: mientras llega la nueva, se sigue
  // viendo la anterior, atenuada, en lugar de vaciar la lista en cada tecla.
  const [shown, setShown] = useState<{ query: string; result: UsersResult }>({ query, result: { kind: "loading" } });

  // showModal y no el atributo open: así es modal (el resto de la página queda inerte) y Esc
  // lo cierra. El foco se pone a mano: React no deja el atributo autofocus en el HTML, y
  // showModal lo llevaría al primer botón ("Cerrar").
  // Si ya está abierto, no: en desarrollo StrictMode corre el efecto dos veces.
  useEffect(() => {
    if (dialog.current && !dialog.current.open) dialog.current.showModal();
    search.current?.focus();
  }, []);

  useEffect(() => {
    if (text.trim() === query) return;
    const timer = setTimeout(() => setQuery(text.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, query]);

  useEffect(() => {
    // Cancela el pedido anterior: una respuesta vieja que llega tarde no pisa a la nueva.
    const controller = new AbortController();
    fetchUsers(query, controller.signal).then((result) => {
      if (!controller.signal.aborted) setShown({ query, result });
    });
    return () => controller.abort();
  }, [query, attempt]);

  const close = () => dialog.current?.close(); // dispara onClose, como Esc

  return (
    <dialog
      ref={dialog}
      className="user-dialog"
      aria-labelledby="user-dialog-title"
      onClose={onClose}
      // El contenido ocupa todo el diálogo: un clic que llega al <dialog> mismo es en el fondo.
      onClick={(event) => event.target === event.currentTarget && close()}
    >
      <div className="user-dialog-body">
        <header>
          <h2 id="user-dialog-title">Elegí un usuario</h2>
          <button className="link" onClick={close}>
            Cerrar
          </button>
        </header>
        <p className="muted">No hay registro: votás y recibís recomendaciones como el usuario que elijas.</p>
        <input
          className="search"
          type="search"
          placeholder="Buscar por nombre, email o id"
          aria-label="Buscar usuario por nombre, email o id"
          maxLength={100}
          ref={search}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <UserResults
          result={shown.result}
          query={shown.query}
          stale={shown.query !== query}
          current={current}
          onChoose={onChoose}
          onRetry={() => {
            setShown({ query, result: { kind: "loading" } });
            setAttempt((n) => n + 1);
          }}
        />
        {current && (
          <p>
            <button className="link" onClick={() => onChoose(null)}>
              Dejar de usar a {current.name}
            </button>
          </p>
        )}
      </div>
    </dialog>
  );
}

function UserResults({
  result,
  query,
  stale,
  current,
  onChoose,
  onRetry,
}: {
  result: UsersResult;
  query: string;
  stale: boolean;
  current: User | null;
  onChoose: (user: User) => void;
  onRetry: () => void;
}) {
  if (result.kind === "loading") {
    return <p className="muted">Cargando usuarios…</p>;
  }
  if (result.kind === "failed") {
    // 503: el backend todavía los está cargando, o Mongo no responde. No se sabe cuál.
    const reason = result.status === 503 ? "todavía no están disponibles" : result.reason;
    return (
      <p className="muted" role="alert">
        No pudimos cargar los usuarios ({reason}) · <button className="link" onClick={onRetry}>Reintentar</button>
      </p>
    );
  }
  const { items, total } = result.data;
  if (total === 0) {
    return <p className="muted">No hay usuarios que coincidan con "{query}".</p>;
  }
  return (
    <div className={stale ? "user-results stale" : "user-results"}>
      <ul className="user-list">
        {items.map((item) => (
          <li key={item.id}>
            <button aria-current={item.id === current?.id} onClick={() => onChoose({ id: item.id, name: item.name })}>
              <strong>{item.name}</strong>
              <span className="muted">{item.id}</span>
              {item.preloaded && <span className="tag">nuevo, sin votos</span>}
            </button>
          </li>
        ))}
      </ul>
      {items.length < total && (
        <p className="muted">
          Se muestran {items.length} de {countFormat.format(total)}. Escribí más para acotar.
        </p>
      )}
    </div>
  );
}
