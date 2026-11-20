"""Recomendaciones por petición (docs/recomendador.md 9.3).

Funciones puras sobre el Catalog y la Quality ya calculados. Ninguna recorre el
catálogo con similitudes: leen las listas de vecinos precalculadas (R15), y MMR
compara solo las ≈ 200 candidatas entre sí.

    votos del usuario ─▶ pesos (estrellas − punto medio) ─▶ acc sobre los vecinos
        ─▶ 200 candidatas ─▶ + β·WRz ─▶ MMR ─▶ relleno con el ranking ─▶ items
"""

from dataclasses import dataclass

import numpy as np

from app import params
from app.index import Catalog, Quality

CONTENT = "content"
RANKING = "ranking"


@dataclass(frozen=True)
class Item:
    row: int
    score: float
    because: int | None = None  # fila de la película votada que más aportó


def for_user(catalog: Catalog, quality: Quality, votes: list[tuple[int, int]], limit: int) -> tuple[str, list[Item]]:
    """votes: (fila, estrellas) de los votos activos del usuario, sobre películas activas.

    Devuelve el origen ("content" o "ranking") y hasta `limit` items.
    """
    if not votes:
        return RANKING, ranking(quality, limit)
    middle = midpoint(votes, quality)
    return from_weights(catalog, quality, [(row, stars - middle) for row, stars in votes], limit)


def midpoint(votes: list[tuple[int, int]], quality: Quality) -> float:
    """Promedio del usuario corregido hacia C (4.2): un solo voto no deja el perfil vacío."""
    total = sum(stars for _, stars in votes)
    return (total + params.K_USER * quality.mean_vote) / (len(votes) + params.K_USER)


def from_weights(
    catalog: Catalog, quality: Quality, weighted: list[tuple[int, float]], limit: int
) -> tuple[str, list[Item]]:
    """Pasos 4 a 10 de 9.3, con el peso de cada voto ya calculado."""
    voted = np.array([row for row, _ in weighted], dtype=np.int64)
    if not any(weight > 0 for _, weight in weighted):
        # Solo votos negativos: el ranking, sin lo votado ni los vecinos de lo votado.
        excluded = set(voted.tolist()) | set(catalog.neighbors[voted].ravel().tolist())
        return RANKING, ranking(quality, limit, excluded)

    n = len(catalog)
    acc = np.zeros(n)
    best = np.full(n, -np.inf)
    because = np.full(n, -1, dtype=np.int64)
    for row, weight in weighted:
        neighbors = catalog.neighbors[row]
        contribution = weight * catalog.neighbor_scores[row].astype(np.float64)
        acc[neighbors] += contribution  # una lista de vecinos no repite filas
        better = contribution > best[neighbors]
        best[neighbors[better]] = contribution[better]
        because[neighbors[better]] = row
    acc[voted] = 0  # lo votado no se recomienda

    candidates = np.flatnonzero(acc > 0)
    if len(candidates) > params.CANDIDATES:
        candidates = candidates[np.argpartition(-acc[candidates], params.CANDIDATES - 1)[: params.CANDIDATES]]
    scores = acc[candidates] + params.BETA * quality.wr_z[candidates]
    order = np.argsort(-scores, kind="stable")
    candidates, scores = candidates[order], scores[order]

    picked = mmr(scores, catalog.similarity(candidates), limit)
    items = [Item(int(candidates[i]), float(scores[i]), int(because[candidates[i]])) for i in picked]
    if len(items) < limit:
        # Candidatas que no alcanzan: se completa con el ranking. Su puntaje es el que
        # tendría una candidata sin parecido (acc = 0): solo el piso β·WRz.
        excluded = set(voted.tolist()) | {item.row for item in items}
        items += [
            Item(item.row, float(params.BETA * quality.wr_z[item.row]))
            for item in ranking(quality, limit - len(items), excluded)
        ]
    return CONTENT, items


def similar(catalog: Catalog, quality: Quality, row: int, limit: int) -> list[Item]:
    """"Películas similares": la lista de vecinas, con β·WRz y MMR."""
    neighbors = catalog.neighbors[row]
    scores = catalog.neighbor_scores[row].astype(np.float64) + params.BETA * quality.wr_z[neighbors]
    order = np.argsort(-scores, kind="stable")
    neighbors, scores = neighbors[order], scores[order]
    picked = mmr(scores, catalog.similarity(neighbors), limit)
    return [Item(int(neighbors[i]), float(scores[i])) for i in picked]


def ranking(quality: Quality, limit: int, excluded: set[int] = frozenset(), genre: str | None = None) -> list[Item]:
    """Las primeras `limit` por WR, globales o de un género, sin las excluidas."""
    rows = quality.ranking if genre is None else quality.by_genre[genre]
    items = []
    for row in rows:  # sin tolist(): se corta apenas junta `limit`, no convierte 20.000
        row = int(row)
        if len(items) == limit:
            break
        if row not in excluded:
            items.append(Item(row, float(quality.wr[row])))
    return items


def mmr(scores: np.ndarray, sim: np.ndarray, limit: int, lam: float = params.LAMBDA) -> list[int]:
    """Elige de a una: cada candidata vale λ·puntaje_n − (1 − λ)·(su mayor similitud_n con las elegidas).

    puntaje_n: mín–máx a 0–1 entre las candidatas. similitud_n: sim dividida por su máximo.
    Devuelve los índices elegidos, en orden.
    """
    n = len(scores)
    if n == 0 or limit <= 0:
        return []
    scores_n = (scores - scores.min()) / (scores.max() - scores.min() + 1e-9)
    sim_n = sim / (np.abs(sim).max() + 1e-9)
    free = np.ones(n, dtype=bool)
    max_sim = np.full(n, -np.inf)  # -inf: todavía no hay elegidas, la penalización es 0
    chosen = []
    for _ in range(min(limit, n)):
        penalty = np.where(np.isinf(max_sim), 0.0, max_sim)
        value = np.where(free, lam * scores_n - (1 - lam) * penalty, -np.inf)
        best = int(np.argmax(value))
        chosen.append(best)
        free[best] = False
        max_sim = np.maximum(max_sim, sim_n[best])
    return chosen
