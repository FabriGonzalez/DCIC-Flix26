"""Ficha de una película: GET /movies/{id} (README, "Ficha").

Mismo criterio que el catálogo (catalog.py): durante la limpieza se lee el crudo, y cada
campo se devuelve solo si cumple el contrato limpio; si no, sale null.
"""

from typing import Any

from bson import ObjectId
from pymongo import AsyncMongoClient

from app import catalog


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _texts(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def to_detail(document: dict) -> dict:
    """Una película de Mongo (limpia o cruda) a la forma que muestra la ficha."""
    imdb = document.get("imdb")
    awards = document.get("awards")
    rated = _text(document.get("rated"))
    return {
        **catalog.to_card(document),
        # fullplot es la versión larga; cuando falta (≈300 películas) queda la corta.
        "plot": _text(document.get("fullplot")) or _text(document.get("plot")),
        "runtime": _positive_int(document.get("runtime")),
        # El contrato la garantiza en mayúsculas (A20): en el crudo, "Unrated" no cumple.
        "rated": rated if rated is not None and rated == rated.upper() else None,
        "directors": _texts(document.get("directors")),
        "cast": _texts(document.get("cast")),
        "countries": _texts(document.get("countries")),
        "languages": _texts(document.get("languages")),
        "imdbVotes": _positive_int(imdb.get("votes")) if isinstance(imdb, dict) else None,
        "awards": _text(awards.get("text")) if isinstance(awards, dict) else None,
    }


async def get_movie(mongo: AsyncMongoClient, movie_id: str) -> dict | None:
    """La ficha, o None si el id no es válido o no existe. Lanza PyMongoError si Mongo no responde.

    Una copia duplicada descartada (A5) devuelve la película en la que se fusionó, con el id
    de esa: el frontend corrige la URL. El contrato garantiza que `mergedInto` apunta a una
    película activa, así que se sigue un solo salto.
    """
    if not ObjectId.is_valid(movie_id):
        return None
    collection = mongo.get_default_database()[catalog.COLLECTION]
    document = await collection.find_one({"_id": ObjectId(movie_id)})
    if document is not None and document.get("deleted") is True:
        merged_into = document.get("mergedInto")
        if not isinstance(merged_into, ObjectId):
            return None
        document = await collection.find_one({"_id": merged_into, **catalog.ACTIVE})
    return to_detail(document) if document is not None else None
