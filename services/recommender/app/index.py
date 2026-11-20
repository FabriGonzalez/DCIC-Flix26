"""Índice del recomendador: señales, calibración, vecinos y WR (docs/recomendador.md 9.2).

Funciones puras sobre arrays: no leen Mongo ni disco, así que se prueban con un
catálogo de juguete y se comparan contra analysis/recomendador/pesos.py.

    películas activas + vectores del plot ──▶ build_catalog ──▶ Catalog   (al indexar)
        señales P, G, T · calibración · 100 vecinos por película · Q de IMDb
    votos por película (cantidad y suma) ──▶ build_quality ──▶ Quality   (al indexar y cada 60 s)
        WR · WR estandarizado · rankings global y por género

Cada fila de las matrices es una película activa, en el orden de `Catalog.ids`.

Los valores que no cumplen el contrato de la limpieza (ANOMALIAS, sección 7) se
descartan y se cuentan en `Catalog.anomalies`: con la base limpia tiene que quedar vacío.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from app import params

PEOPLE_FIELDS = ("directors", "cast", "writers")
NEUTRAL_VOTE = 3.0  # C sin ningún voto: el medio de la escala 1–5
_EPS = 1e-9
_ROLE = re.compile(r"\s*\(.*$")


@dataclass(frozen=True, eq=False)
class Catalog:
    """Lo que depende solo del contenido: los votos nuevos no lo cambian."""

    ids: list[str]  # movie_id de cada fila
    rows: dict[str, int]  # movie_id → fila
    genres: list[str]  # nombre de cada columna de G
    plot: np.ndarray  # P: (N, 384), filas de largo 1, o de ceros si no hay plot
    G: np.ndarray  # (N, géneros), filas de largo 1, o de ceros sin géneros
    T: sparse.csr_matrix  # personas con TF-IDF, filas de largo 1
    scales: tuple[float, float, float]  # q_plot, q_géneros, q_personas
    prior_q: np.ndarray  # Q de IMDb con su bayesiano; NaN si no hay IMDb
    neighbors: np.ndarray  # (N, K) int32: filas de las K más parecidas, de mayor a menor
    neighbor_scores: np.ndarray  # (N, K) float32: su S
    anomalies: Counter

    def __len__(self) -> int:
        return len(self.ids)

    def similarity(self, rows: np.ndarray) -> np.ndarray:
        """S (fórmula de 9.2) entre las filas dadas: (n, n). Para MMR, sobre ≈ 200 candidatas."""
        return _combined(self.plot, self.G, self.T, self.scales, rows, rows)

    def genre_counts(self) -> dict[str, int]:
        return {g: int(n) for g, n in zip(self.genres, (self.G > 0).sum(axis=0))}


@dataclass(frozen=True, eq=False)
class Quality:
    """Lo que depende de los votos de todos: se recalcula cada 60 s (R18)."""

    wr: np.ndarray  # (N,) promedio bayesiano sobre el punto de partida de IMDb
    wr_z: np.ndarray  # (N,) WR estandarizado, para el piso β·WRz
    mean_vote: float  # C
    q5: tuple[float, float] | None  # a, b de Q₅ = a·Q + b; None si no se pudo ajustar
    votes: int
    ranking: np.ndarray  # filas por WR, de mayor a menor
    by_genre: dict[str, np.ndarray]  # lo mismo, solo con las películas de cada género


# --- Catálogo ---------------------------------------------------------------------------


def build_catalog(movies: list[dict], plot_vectors: np.ndarray) -> Catalog:
    """movies: documentos de `movies` activos. plot_vectors: (N, d), fila i = plot de movies[i].

    Una fila de ceros en plot_vectors es "sin plot": ese término vale 0 (R16).
    """
    anomalies: Counter = Counter()
    ids = [str(doc["_id"]) for doc in movies]
    plot = _unit_rows(np.asarray(plot_vectors, dtype=np.float32))
    genres, G = _genre_matrix([_genres(doc, anomalies) for doc in movies])
    T = people_matrix([_people(doc, anomalies) for doc in movies])
    prior_q = imdb_prior([_imdb(doc, anomalies) for doc in movies])
    scales = (calibrate(plot), calibrate(G), calibrate(T))
    neighbors, neighbor_scores = _neighbors(plot, G, T, scales)
    return Catalog(
        ids=ids,
        rows={movie_id: i for i, movie_id in enumerate(ids)},
        genres=genres,
        plot=plot,
        G=G,
        T=T,
        scales=scales,
        prior_q=prior_q,
        neighbors=neighbors,
        neighbor_scores=neighbor_scores,
        anomalies=anomalies,
    )


def strip_role(name: str) -> str:
    """'Stephen King (novel)' → 'Stephen King' (ANOMALIAS, A18)."""
    return _ROLE.sub("", name).strip()


def people_matrix(people: list[set[str]]) -> sparse.csr_matrix:
    """TF-IDF de personas (4.1): una columna por nombre que aparece en 2 o más películas.

    Cada nombre pesa log(N / df); los de una sola película nunca coinciden con nada.
    """
    n = len(people)
    df = Counter(name for names in people for name in names)
    column = {name: k for k, name in enumerate(sorted(name for name, c in df.items() if c >= 2))}
    rows, cols, values = [], [], []
    for i, names in enumerate(people):
        for name in names:
            if name in column:
                rows.append(i)
                cols.append(column[name])
                values.append(math.log(n / df[name]))
    T = sparse.csr_matrix((values, (rows, cols)), shape=(n, len(column)), dtype=np.float32)
    norms = np.sqrt(np.asarray(T.multiply(T).sum(axis=1)).ravel())
    return sparse.diags(1 / np.maximum(norms, _EPS)).dot(T).tocsr().astype(np.float32)


def imdb_prior(imdb: list[tuple[float, float] | None]) -> np.ndarray:
    """Q = (V·rating + M·Ī) / (V + M), con Ī el promedio de imdb.rating del catálogo (3.3)."""
    rated = [r for r in imdb if r is not None]
    if not rated:
        return np.full(len(imdb), np.nan)
    mean_rating = sum(r for r, _ in rated) / len(rated)
    m = params.M_IMDB
    return np.array([np.nan if r is None else (r[1] * r[0] + m * mean_rating) / (r[1] + m) for r in imdb])


def calibrate(
    X,
    *,
    rank: int = params.CALIBRATION_RANK,
    sample: int = params.CALIBRATION_SAMPLE,
    seed: int = params.CALIBRATION_SEED,
) -> float:
    """Cuánto vale "un buen vecino" según una señal (4.1).

    Mediana, sobre `sample` películas al azar, de la similitud con su `rank`-ésima más
    parecida. Se excluyen las que no tienen `rank` vecinas con similitud > 0.
    """
    n = X.shape[0]
    if n < 2:
        return 1.0
    rows = np.random.default_rng(seed).choice(n, size=min(sample, n), replace=False)
    sims = _dot(X[rows], X)
    sims[np.arange(len(rows)), rows] = -np.inf  # sin contarse a sí misma
    k = min(rank, n - 1)
    kth = -np.partition(-sims, k - 1, axis=1)[:, k - 1]  # el k-ésimo más alto, exacto
    positive = kth[kth > 0]
    return float(np.median(positive)) if len(positive) else 1.0


def _genres(doc: dict, anomalies: Counter) -> list[str]:
    value = doc.get("genres")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(g, str) for g in value):
        anomalies["genres no es una lista de textos"] += 1
        return []
    return sorted({g.strip() for g in value if g.strip()})


def _people(doc: dict, anomalies: Counter) -> set[str]:
    names = set()
    for field in PEOPLE_FIELDS:
        value = doc.get(field)
        if value is None:  # las listas que faltan cuentan como vacías
            continue
        if not isinstance(value, list):
            anomalies[f"{field} no es una lista"] += 1
            continue
        for name in value:
            if not isinstance(name, str):
                anomalies[f"{field} con un nombre que no es texto"] += 1
            elif stripped := strip_role(name):
                names.add(stripped)
    return names


def _imdb(doc: dict, anomalies: Counter) -> tuple[float, float] | None:
    imdb = doc.get("imdb")
    if imdb is None:
        return None
    if not isinstance(imdb, dict):
        anomalies["imdb no es un documento"] += 1
        return None
    rating, votes = imdb.get("rating"), imdb.get("votes")
    if rating is None or votes is None:
        return None
    if not (_is_number(rating) and 0 <= rating <= 10 and _is_number(votes) and votes >= 0):
        anomalies["imdb.rating o imdb.votes fuera de contrato"] += 1
        return None
    return float(rating), float(votes)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _genre_matrix(genre_lists: list[list[str]]) -> tuple[list[str], np.ndarray]:
    names = sorted({g for gs in genre_lists for g in gs})
    column = {g: k for k, g in enumerate(names)}
    G = np.zeros((len(genre_lists), len(names)), np.float32)
    for i, gs in enumerate(genre_lists):
        G[i, [column[g] for g in gs]] = 1
    return names, _unit_rows(G)


def _unit_rows(X: np.ndarray) -> np.ndarray:
    return X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), _EPS)


def _dot(A, B) -> np.ndarray:
    """A·Bᵀ denso, sea A y B densas o dispersas."""
    product = A @ B.T
    return product.toarray() if sparse.issparse(product) else np.asarray(product)


def _combined(P, G, T, scales, rows, cols=None) -> np.ndarray:
    """S = 0,2·(P·Pᵀ)/q_plot + 0,4·(G·Gᵀ)/q_géneros + 0,4·min((T·Tᵀ)/q_personas, 2)."""
    q_plot, q_genres, q_people = scales
    Pc, Gc, Tc = (P, G, T) if cols is None else (P[cols], G[cols], T[cols])
    S = (params.W_PLOT / q_plot) * (P[rows] @ Pc.T)
    S += (params.W_GENRES / q_genres) * (G[rows] @ Gc.T)
    S += params.W_PEOPLE * np.minimum(_dot(T[rows], Tc) / q_people, params.PEOPLE_CAP)
    return S


def _neighbors(P, G, T, scales) -> tuple[np.ndarray, np.ndarray]:
    """Las K de mayor S de cada película, sin ella misma, en bloques de filas (7.1).

    El bloque evita armar la matriz completa: 20.000 × 20.000 son ≈ 1,6 GB.
    """
    n = P.shape[0]
    k = min(params.NEIGHBORS, n - 1)
    neighbors = np.empty((n, max(k, 0)), np.int32)
    scores = np.empty((n, max(k, 0)), np.float32)
    if k <= 0:
        return neighbors, scores
    for start in range(0, n, params.NEIGHBORS_BLOCK):
        rows = np.arange(start, min(start + params.NEIGHBORS_BLOCK, n))
        S = _combined(P, G, T, scales, rows)
        S[np.arange(len(rows)), rows] = -np.inf
        top = np.argpartition(-S, k - 1, axis=1)[:, :k]
        values = np.take_along_axis(S, top, axis=1)
        order = np.argsort(-values, axis=1, kind="stable")
        neighbors[rows] = np.take_along_axis(top, order, axis=1)
        scores[rows] = np.take_along_axis(values, order, axis=1)
    return neighbors, scores


# --- Calidad ----------------------------------------------------------------------------


def build_quality(catalog: Catalog, counts: np.ndarray, sums: np.ndarray) -> Quality:
    """counts[i], sums[i]: cantidad y suma de estrellas de los votos activos de la fila i (3.3)."""
    counts = np.asarray(counts, dtype=np.float64)
    sums = np.asarray(sums, dtype=np.float64)
    total = counts.sum()
    mean_vote = float(sums.sum() / total) if total else NEUTRAL_VOTE
    has_q = ~np.isnan(catalog.prior_q)
    q5 = _q5_fit(catalog.prior_q[has_q], counts[has_q], sums[has_q])
    prior = np.full(len(catalog), mean_vote)
    if q5 is not None:
        a, b = q5
        prior[has_q] = a * catalog.prior_q[has_q] + b
    wr = (sums + params.M_OWN * prior) / (counts + params.M_OWN)
    std = wr.std()
    wr_z = (wr - wr.mean()) / std if std > 0 else np.zeros_like(wr)
    ranking = np.argsort(-wr, kind="stable").astype(np.int32)
    has_genre = catalog.G[ranking] > 0
    by_genre = {g: ranking[has_genre[:, k]] for k, g in enumerate(catalog.genres)}
    return Quality(
        wr=wr,
        wr_z=wr_z,
        mean_vote=mean_vote,
        q5=q5,
        votes=int(total),
        ranking=ranking,
        by_genre=by_genre,
    )


def _q5_fit(q: np.ndarray, counts: np.ndarray, sums: np.ndarray) -> tuple[float, float] | None:
    """Regresión lineal de cada voto sobre el Q de su película: voto ≈ a·Q + b.

    Es la de mínimos cuadrados sobre los votos uno por uno (np.polyfit), pero con los
    agregados por película: los n votos de una película comparten su Q, así que
    Σx = Σ n·Q, Σx² = Σ n·Q², Σy = Σ suma y Σxy = Σ Q·suma.
    """
    n = counts.sum()
    sx, sxx = (counts * q).sum(), (counts * q * q).sum()
    sy, sxy = sums.sum(), (q * sums).sum()
    denominator = n * sxx - sx * sx
    if n < 2 or denominator <= _EPS * max(n * sxx, 1.0):
        return None
    a = (n * sxy - sx * sy) / denominator
    return float(a), float((sy - a * sx) / n)
