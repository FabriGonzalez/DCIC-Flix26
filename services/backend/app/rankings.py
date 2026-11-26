"""Filas por género arriba del catálogo: GET /rankings (docs/recomendador.md 3.5, R6).

Una fila por género con lo mejor según el ranking bayesiano (WR) del recommender, de los
géneros más grandes a los más chicos. Un solo pedido del frontend: el backend pide los
rankings en paralelo y arma todas las tarjetas con una sola consulta a Mongo. El orden de
las filas queda acá porque es presentación (más adelante lo ordenan los géneros del usuario).
"""

import asyncio

import httpx
from pymongo import AsyncMongoClient

from app import catalog, recommender

PER_ROW = 12  # como las similares: la grilla queda completa en 2, 3, 4 o 6 columnas

# Los mismos que deja afuera el onboarding (docs/recomendador.md 3.5): Short es un formato,
# no un tema; News (43) y Talk-Show (1) son demasiado chicos para una fila.
EXCLUDED = {"Short", "News", "Talk-Show"}


async def genre_ids(http: httpx.AsyncClient, url: str) -> list[tuple[str, list[str]]]:
    """(género, ids en orden de WR) por cada género con fila, de más a menos películas."""
    genres = await recommender.get(http, url, "/genres")
    # /genres ya viene ordenado por cantidad de películas.
    names = [g["genre"] for g in genres["items"] if g["genre"] not in EXCLUDED]
    rankings = await asyncio.gather(
        *(recommender.get(http, url, "/rankings", {"genre": name, "limit": PER_ROW}) for name in names)
    )
    return [(name, [item["movie_id"] for item in body["items"]]) for name, body in zip(names, rankings)]


async def list_rows(http: httpx.AsyncClient, url: str, mongo: AsyncMongoClient) -> list[dict]:
    """Lanza RecommenderUnavailable o PyMongoError."""
    rows = await genre_ids(http, url)
    # Una película puede estar en varias filas (Drama y Crime): se pide una vez.
    unique = list(dict.fromkeys(i for _, ids in rows for i in ids))
    found = await catalog.cards_by_id(mongo, unique)
    result = [{"genre": name, "items": [found[i] for i in ids if i in found]} for name, ids in rows]
    return [row for row in result if row["items"]]
