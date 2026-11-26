// El usuario elegido, para toda la app (README, "Usuarios"): no hay registro, se elige uno
// de la lista. Lo leen el formulario de voto y, más adelante, las recomendaciones.
//
// Vive en localStorage y no en la URL: un link compartido no tiene que llevar tu usuario.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import type { User } from "./users";

export interface ChosenUser {
  user: User | null; // null: todavía no eligió
  choose: (user: User | null) => void;
}

const STORAGE_KEY = "dcicflix.user";

function isUser(value: unknown): value is User {
  const candidate = value as User | null;
  return typeof candidate?.id === "string" && typeof candidate.name === "string";
}

/** Lo guardado, o null si no hay nada o no es un usuario (otra versión, editado a mano). */
function readStored(): User | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    return isUser(value) ? { id: value.id, name: value.name } : null;
  } catch {
    // JSON roto, o el navegador no deja usar localStorage (algunos modos privados).
    return null;
  }
}

function store(user: User | null): void {
  try {
    if (user === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Sin localStorage, el usuario dura hasta recargar: la app funciona igual.
  }
}

const UserContext = createContext<ChosenUser | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(readStored);

  // Si se cambia en otra pestaña, esta lo sigue: si no, cada pestaña votaría con un usuario
  // distinto sin que se note. El evento llega solo a las otras pestañas, no a la que escribió.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY || event.key === null) setUser(readStored());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const choose = useCallback((next: User | null) => {
    store(next);
    setUser(next);
  }, []);
  const value = useMemo(() => ({ user, choose }), [user, choose]);
  return <UserContext value={value}>{children}</UserContext>;
}

export function useUser(): ChosenUser {
  const chosen = useContext(UserContext);
  if (chosen === null) {
    throw new Error("useUser fuera de UserProvider");
  }
  return chosen;
}
