// Usuarios según GET /api/users (README, "Usuarios").

import { getJson, type Fetched } from "./api";

/** Lo que distingue a dos usuarios es el id: los nombres se repiten. */
export interface User {
  id: string;
  name: string;
}

export interface UserItem extends User {
  preloaded: boolean; // uno de los nuevos, sin votos (usr_2001 a usr_2005)
}

export interface UsersPage {
  items: UserItem[]; // hasta 20
  total: number;
}

export type UsersResult = { kind: "loading" } | Fetched<UsersPage>;

export function fetchUsers(query: string, signal: AbortSignal): Promise<UsersResult> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  return getJson<UsersPage>(`/api/users?${params}`, signal);
}
