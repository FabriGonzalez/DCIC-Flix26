import { useId, useState, type FormEvent } from "react";

import { useSystemStatus, type StatusResult } from "./status";
import { useUser } from "./user";
import type { User } from "./users";
import { MAX_COMMENT_LENGTH, sendVote, type VoteResult } from "./votes";

const countFormat = new Intl.NumberFormat("es-AR");

/** "Tu voto", en la ficha. Vota en nombre del usuario elegido en el encabezado. */
export function VoteForm({ movieId }: { movieId: string }) {
  const { user, openPicker } = useUser();
  return (
    <section className="vote-section">
      <h3>Tu voto</h3>
      {user === null ? (
        <p className="muted">
          Para votar, <button className="link" onClick={openPicker}>elegí un usuario</button>.
        </p>
      ) : (
        // key: con otro usuario u otra película, el formulario arranca de cero.
        <VoteFields key={`${user.id}/${movieId}`} movieId={movieId} user={user} />
      )}
    </section>
  );
}

/** Por qué no se puede votar todavía, o null si se puede (README, "Estado del sistema"). */
function blockedReason(status: StatusResult): string | null {
  if (status.kind === "loading") return "Consultando el estado del sistema…";
  if (status.kind === "unknown") return "No pudimos consultar el estado del sistema. Reintentando…";
  if (status.state === "cleaning") return "Estamos limpiando los datos. Vas a poder votar cuando termine la preparación.";
  if (status.state === "indexing") return "Estamos preparando las recomendaciones. Falta poco para poder votar.";
  return null;
}

function VoteFields({ movieId, user }: { movieId: string; user: User }) {
  const { result: status, recheck } = useSystemStatus();
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [outcome, setOutcome] = useState<VoteResult | null>(null);

  const blocked = blockedReason(status);
  // Tras un error que se puede reintentar, el botón lo dice.
  const retry = outcome?.kind === "unavailable" || outcome?.kind === "unknown";

  const edit = (apply: () => void) => {
    apply();
    setOutcome(null); // el mensaje era sobre lo que se envió, no sobre lo que se está escribiendo
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (blocked || sending || rating === null) return;
    setSending(true);
    setOutcome(null);
    try {
      const result = await sendVote(movieId, user.id, rating, comment);
      // 409: con "ready" ya no se consultaba el estado. Se vuelve a consultar, y el formulario
      // queda deshabilitado con el motivo hasta que vuelva a estar listo. Lo escrito se conserva.
      if (result.kind === "not-ready") recheck();
      setOutcome(result);
    } finally {
      setSending(false);
    }
  };

  return (
    <form className="vote" onSubmit={submit}>
      {blocked && (
        <p className="vote-blocked" role="status">
          {blocked}
        </p>
      )}
      {/* Un fieldset deshabilitado deshabilita todo lo de adentro, sin perder lo escrito. */}
      <fieldset className="vote-fields" disabled={blocked !== null}>
        <StarInput value={rating} onChange={(n) => edit(() => setRating(n))} />
        <label className="vote-comment">
          <span>
            Comentario <span className="muted">(opcional)</span>
          </span>
          <textarea
            rows={3}
            maxLength={MAX_COMMENT_LENGTH}
            value={comment}
            onChange={(event) => edit(() => setComment(event.target.value))}
          />
        </label>
        {comment.length > MAX_COMMENT_LENGTH - 500 && (
          <p className="muted vote-count">
            {countFormat.format(comment.length)} de {countFormat.format(MAX_COMMENT_LENGTH)} caracteres
          </p>
        )}
        <div className="vote-actions">
          <button type="submit" disabled={sending || rating === null}>
            {sending ? "Enviando…" : retry ? "Reintentar" : "Enviar voto"}
          </button>
          {rating === null && !blocked && <span className="muted">Elegí de 1 a 5 estrellas.</span>}
        </div>
      </fieldset>
      {outcome && <Outcome result={outcome} />}
    </form>
  );
}

function Outcome({ result }: { result: VoteResult }) {
  switch (result.kind) {
    case "accepted":
      return (
        <p className="vote-outcome ok" role="status">
          Tu voto se envió. Va a aparecer en las reseñas en unos segundos.
        </p>
      );
    case "not-ready":
      return (
        <p className="vote-outcome error" role="alert">
          No se pudo enviar: el sistema dejó de estar listo para votar. Lo que escribiste queda acá.
        </p>
      );
    case "unavailable":
      return (
        <p className="vote-outcome error" role="alert">
          No se pudo enviar: el servicio no responde. Podés reintentar: si el voto había llegado, el nuevo lo
          reemplaza.
        </p>
      );
    case "unknown":
      return (
        <p className="vote-outcome error" role="alert">
          No sabemos si el voto llegó ({result.reason}). Podés reintentar: si había llegado, el nuevo lo reemplaza.
        </p>
      );
    case "rejected": {
      // 404: el usuario o la película ya no existen. 422: el formato (no debería pasar: el
      // formulario no deja enviar nada inválido). El detail del backend dice cuál.
      const detail = result.detail ?? (result.status === 404 ? "no existe el usuario o la película" : `HTTP ${result.status}`);
      return (
        <p className="vote-outcome error" role="alert">
          No se pudo enviar: {detail}.
        </p>
      );
    }
  }
}

/** Cinco radios: el teclado (flechas) y los lectores de pantalla funcionan sin código extra. */
function StarInput({ value, onChange }: { value: number | null; onChange: (rating: number) => void }) {
  const name = useId();
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? value ?? 0;
  return (
    <fieldset className="stars-input" onMouseLeave={() => setHover(null)}>
      <legend>Puntaje</legend>
      {[1, 2, 3, 4, 5].map((n) => (
        <label key={n} className={n <= shown ? "on" : undefined} onMouseEnter={() => setHover(n)}>
          <input type="radio" name={name} value={n} checked={value === n} onChange={() => onChange(n)} />
          <span aria-hidden="true">★</span>
          <span className="visually-hidden">{n === 1 ? "1 estrella" : `${n} estrellas`}</span>
        </label>
      ))}
    </fieldset>
  );
}
