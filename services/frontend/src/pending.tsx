// Votos enviados que todavía no aparecieron en una lectura de las reseñas (README, "Voto con
// reseña"). El 202 llega antes de que el ingest-consumer guarde el voto: releer en ese momento
// podría mostrar el voto anterior. En lugar de releer, la ficha muestra el enviado como
// "Enviada" hasta que una lectura traiga la reseña con fecha igual o posterior a votedAt.
//
// En memoria, para toda la app: sobrevive a navegar entre pantallas, no a recargar. Tras
// recargar se ve lo guardado, que es el voto nuevo o, si todavía no se guardó, el anterior.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import type { AcceptedVote } from "./votes";

export interface PendingVotes {
  get: (userId: string, movieId: string) => AcceptedVote | null;
  add: (vote: AcceptedVote) => void; // reemplaza al anterior del mismo usuario y película
  /** Lo saca, salvo que ya lo haya reemplazado uno más nuevo. */
  clear: (vote: AcceptedVote) => void;
}

const key = (userId: string, movieId: string) => `${userId}/${movieId}`;

const PendingContext = createContext<PendingVotes | null>(null);

export function PendingVotesProvider({ children }: { children: ReactNode }) {
  const [votes, setVotes] = useState<ReadonlyMap<string, AcceptedVote>>(new Map());

  const get = useCallback((userId: string, movieId: string) => votes.get(key(userId, movieId)) ?? null, [votes]);
  const add = useCallback((vote: AcceptedVote) => {
    setVotes((previous) => new Map(previous).set(key(vote.userId, vote.movieId), vote));
  }, []);
  const clear = useCallback((vote: AcceptedVote) => {
    setVotes((previous) => {
      const k = key(vote.userId, vote.movieId);
      if (previous.get(k)?.votedAt !== vote.votedAt) return previous;
      const next = new Map(previous);
      next.delete(k);
      return next;
    });
  }, []);

  const value = useMemo(() => ({ get, add, clear }), [get, add, clear]);
  return <PendingContext value={value}>{children}</PendingContext>;
}

export function usePendingVotes(): PendingVotes {
  const pending = useContext(PendingContext);
  if (pending === null) {
    throw new Error("usePendingVotes fuera de PendingVotesProvider");
  }
  return pending;
}
