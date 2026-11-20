"""Lecturas de MongoDB del recommender (docs/recomendador.md, secciones 8 y 9.2).

Todas son async y no reintentan: el reintento lo decide quien llama (lifecycle.py).
El recommender solo lee; la marca de limpieza la escribe el cleaning-agent.
"""

from collections import Counter
from dataclasses import dataclass

import numpy as np
from pymongo.asynchronous.database import AsyncDatabase

from dcicflix_common import cleaning

from app.index import Catalog

# Los campos de `movies` que usa el recomendador (sección 8), sin `deleted`, que va en el filtro.
MOVIE_FIELDS = {field: 1 for field in ("plot", "genres", "directors", "cast", "writers", "imdb.rating", "imdb.votes")}

# Un voto válido tiene estrellas enteras de 1 a 5 (ANOMALIAS, sección 7). `$in` compara
# números sin mirar el tipo: 5 y 5.0 pasan, "5" y 4.5 no.
_VALID_RATING = {"$in": ["$rating", [1, 2, 3, 4, 5]]}
_VOTE_TOTALS = [
    {"$match": {"deleted": False}},
    {
        "$group": {
            "_id": "$movie_id",
            "count": {"$sum": {"$cond": [_VALID_RATING, 1, 0]}},
            "sum": {"$sum": {"$cond": [_VALID_RATING, "$rating", 0]}},
            "invalid": {"$sum": {"$cond": [_VALID_RATING, 0, 1]}},
        }
    },
]


@dataclass(frozen=True)
class VoteTotals:
    counts: np.ndarray  # votos válidos de cada fila del catálogo
    sums: np.ndarray  # suma de sus estrellas
    anomalies: Counter  # votos descartados, por motivo


async def read_flag(db: AsyncDatabase) -> str | None:
    """El estado de la marca de limpieza, o None si todavía no existe."""
    doc = await db[cleaning.COLLECTION].find_one({"_id": cleaning.DOCUMENT_ID})
    return None if doc is None else doc.get(cleaning.STATUS_FIELD)


async def read_all_plots(db: AsyncDatabase) -> list:
    """El `plot` de todas las películas, activas o no (R17): se embeben antes de la limpieza."""
    return [doc.get("plot") async for doc in db.movies.find({}, {"_id": 0, "plot": 1})]


async def read_movies(db: AsyncDatabase) -> list[dict]:
    """Las películas activas, con los campos de la sección 8."""
    return [doc async for doc in db.movies.find({"deleted": False}, MOVIE_FIELDS)]


async def read_vote_totals(db: AsyncDatabase, catalog: Catalog) -> VoteTotals:
    """Cantidad y suma de los votos activos de cada película del catálogo.

    Agrega en Mongo: viaja una fila por película (≈ 20.000), no un documento por voto.
    """
    counts, sums = np.zeros(len(catalog)), np.zeros(len(catalog))
    anomalies: Counter = Counter()
    async for group in await db.reviews.aggregate(_VOTE_TOTALS):
        if group["invalid"]:
            anomalies["reviews.rating"] += group["invalid"]
        row = catalog.rows.get(str(group["_id"]))
        if row is None:
            if group["count"]:
                anomalies["reviews.movie_id sin película activa"] += group["count"]
        else:
            counts[row], sums[row] = group["count"], group["sum"]
    return VoteTotals(counts, sums, anomalies)
