import { Link } from "react-router";

export function NotFound({ message = "Esta página no existe." }: { message?: string }) {
  return (
    <div className="empty">
      <p className="muted">{message}</p>
      <Link to="/">Volver al catálogo</Link>
    </div>
  );
}
