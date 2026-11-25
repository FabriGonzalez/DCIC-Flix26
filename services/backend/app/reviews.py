"""Reseñas de una película: GET /movies/{id}/reviews (README, "Ficha").

Mismo criterio que el catálogo: se valida contra el contrato (analysis/ANOMALIAS.md,
sección 7) y lo que no cumple sale null. Una reseña activa se muestra aunque le falte una
parte: `commentHidden` oculta solo el texto y `rating: null` (sin LLM) solo las estrellas.
"""

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import AsyncMongoClient

from app import catalog

COLLECTION = "reviews"
# Hoy el máximo es 42 por película: el tope es una protección, no una paginación.
LIMIT = 100

# Solo lo que muestra la ficha. user_email no sale nunca de Mongo.
REVIEW_FIELDS = {"user_name": 1, "rating": 1, "comment": 1, "commentHidden": 1, "date": 1, "datePrecision": 1}


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    # pymongo devuelve las fechas en UTC sin zona. Sin la Z, el navegador la leería como
    # hora local y podría mostrar el día anterior.
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def to_review(document: dict) -> dict:
    """Una reseña de Mongo (limpia o cruda) a la forma que muestra la ficha."""
    name = document.get("user_name")
    rating = document.get("rating")
    comment = document.get("comment")
    date = _iso_date(document.get("date"))
    precision = document.get("datePrecision")
    return {
        "id": str(document["_id"]),
        "userName": name.strip() if isinstance(name, str) and name.strip() else None,
        # '4' en texto, 10 o 999 (B5, B14) no cumplen: salen null.
        "rating": rating if isinstance(rating, int) and not isinstance(rating, bool) and 1 <= rating <= 5 else None,
        "comment": (
            comment.strip()
            if document.get("commentHidden") is not True and isinstance(comment, str) and comment.strip()
            else None
        ),
        "date": date,
        # El crudo no tiene el campo: una fecha que ya es Date es de día (las `circa` son texto).
        "datePrecision": None if date is None else precision if precision in ("day", "year") else "day",
    }


def pipeline(movie_id: ObjectId) -> list[dict]:
    """Las reseñas activas de la película, de la más reciente a la más vieja."""
    return [
        {"$match": {"movie_id": movie_id, **catalog.ACTIVE}},
        {"$project": REVIEW_FIELDS},
        # Igual que los votos del catálogo: en el crudo hay fechas en texto, que Mongo
        # ordenaría mezcladas con las reales. Lo que no es fecha va al final.
        {"$addFields": {"sortDate": {"$cond": [{"$eq": [{"$type": "$date"}, "date"]}, "$date", None]}}},
        {"$sort": {"sortDate": -1, "_id": -1}},
        {"$limit": LIMIT},
    ]


async def list_reviews(mongo: AsyncMongoClient, movie_id: str) -> dict | None:
    """Las reseñas, o None si el id no es válido. Lanza PyMongoError si Mongo no responde.

    No comprueba que la película exista: un id que no es de ninguna da una lista vacía.
    """
    if not ObjectId.is_valid(movie_id):
        return None
    collection = mongo.get_default_database()[COLLECTION]
    oid = ObjectId(movie_id)
    total = await collection.count_documents({"movie_id": oid, **catalog.ACTIVE})
    cursor = await collection.aggregate(pipeline(oid))
    return {"items": [to_review(d) for d in await cursor.to_list()], "total": total}
