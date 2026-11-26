"""Películas similares para la ficha: GET /movies/{id}/similar (README, "Recomendaciones").

El recommender devuelve solo ids, en orden (docs/recomendador.md 9.4); el backend completa
cada tarjeta desde Mongo con el mismo formato que el catálogo.
"""

import logging

import httpx
from bson import ObjectId
from pymongo import AsyncMongoClient

from app import catalog

# Divisible por 2, 3, 4 y 6, como la página del catálogo: la fila de la grilla queda completa.
LIMIT = 12

log = logging.getLogger("backend")


class RecommenderUnavailable(Exception):
    """El recommender no respondió, o respondió 503 (sin índice)."""


async def similar_ids(http: httpx.AsyncClient, url: str, movie_id: str) -> list[str] | None:
    """Los ids similares, en orden; None si el recommender no tiene la película (404)."""
    try:
        response = await http.get(f"{url}/movies/{movie_id}/similar", params={"limit": LIMIT})
    except httpx.HTTPError as exc:
        raise RecommenderUnavailable(str(exc)) from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RecommenderUnavailable(f"HTTP {response.status_code}")
    return [item["movie_id"] for item in response.json()["items"]]


async def cards(mongo: AsyncMongoClient, ids: list[str]) -> list[dict]:
    """Las tarjetas de esos ids, en el mismo orden. Lanza PyMongoError si Mongo no responde.

    El índice se arma con la base ya limpia, así que no debería faltar ninguna. Si falta
    una, se saltea y se anota: mejor una fila más corta que ninguna.
    """
    wanted = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
    collection = mongo.get_default_database()[catalog.COLLECTION]
    cursor = collection.find({"_id": {"$in": wanted}, **catalog.ACTIVE}, catalog.CARD_FIELDS)
    found = {str(d["_id"]): catalog.to_card(d) for d in await cursor.to_list()}
    missing = [i for i in ids if i not in found]
    if missing:
        log.warning("el recommender devolvió películas que no están activas en Mongo: %s", missing)
    return [found[i] for i in ids if i in found]


async def list_similar(
    http: httpx.AsyncClient, url: str, mongo: AsyncMongoClient, movie_id: str
) -> list[dict] | None:
    """None si el id no es válido o el recommender no tiene la película.

    Lanza RecommenderUnavailable o PyMongoError.
    """
    # Validar antes de armar la URL: el id va en el path del pedido al recommender.
    if not ObjectId.is_valid(movie_id):
        return None
    ids = await similar_ids(http, url, movie_id)
    return None if ids is None else await cards(mongo, ids)
