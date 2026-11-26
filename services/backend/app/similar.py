"""Películas similares para la ficha: GET /movies/{id}/similar (README, "Recomendaciones").

El recommender devuelve solo ids, en orden (docs/recomendador.md 9.4); el backend completa
cada tarjeta desde Mongo con el mismo formato que el catálogo.
"""

import httpx
from bson import ObjectId
from pymongo import AsyncMongoClient

from app import catalog, recommender

# Divisible por 2, 3, 4 y 6, como la página del catálogo: la fila de la grilla queda completa.
LIMIT = 12


async def similar_ids(http: httpx.AsyncClient, url: str, movie_id: str) -> list[str] | None:
    """Los ids similares, en orden; None si el recommender no tiene la película (404)."""
    body = await recommender.get(http, url, f"/movies/{movie_id}/similar", {"limit": LIMIT}, missing_ok=True)
    return None if body is None else [item["movie_id"] for item in body["items"]]


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
    if ids is None:
        return None
    found = await catalog.cards_by_id(mongo, ids)
    return [found[i] for i in ids if i in found]
