"""Catálogo para el frontend: GET /movies (README, "Catálogo").

La consigna pide que el catálogo se pueda recorrer en todo momento, también mientras se
limpia. En ese rato `movies` tiene los datos crudos (year en texto, géneros como texto,
duplicados, sin `deleted`) y el cleaning-agent los va reemplazando por _id.

Criterio: el backend no rescata nada, valida. Cada campo se devuelve solo si cumple lo que
garantiza el contrato limpio (analysis/ANOMALIAS.md, sección 7); si no, sale null. Corregir
es trabajo del cleaning-agent: repetir sus reglas acá sería mantenerlas en dos lugares
para cubrir los segundos que dura la limpieza.
"""

import re
from typing import Any

from pymongo import AsyncMongoClient

COLLECTION = "movies"
PAGE_SIZE = 24  # divisible por 2, 3, 4 y 6: la grilla queda completa en cualquier ancho

# Las copias duplicadas tienen deleted: true. $ne y no `deleted: false` porque, durante la
# limpieza, los documentos crudos todavía no tienen el campo.
ACTIVE = {"deleted": {"$ne": True}}

# Solo lo que muestra la tarjeta: no traer plot, cast, tomatoes...
CARD_FIELDS = {"title": 1, "year": 1, "poster": 1, "genres": 1, "imdb.rating": 1, "imdb.votes": 1}


def _is_number(value: Any) -> bool:
    # bool es subclase de int en Python: True no es un año.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_card(document: dict) -> dict:
    """Una película de Mongo (limpia o cruda) a la forma que muestra el frontend."""
    title = document.get("title")
    year = document.get("year")
    poster = document.get("poster")
    genres = document.get("genres")
    imdb = document.get("imdb")
    rating = imdb.get("rating") if isinstance(imdb, dict) else None
    return {
        "id": str(document["_id"]),
        "title": title if isinstance(title, str) else None,
        "year": year if isinstance(year, int) and not isinstance(year, bool) and year > 0 else None,
        "poster": poster if isinstance(poster, str) and poster.startswith("https://") else None,
        "genres": [g for g in genres if isinstance(g, str)] if isinstance(genres, list) else [],
        # La escala ×10 del crudo (72 en vez de 7,2) es un número, pero no cumple 0–10.
        "imdbRating": rating if _is_number(rating) and 0 < rating <= 10 else None,
    }


def title_filter(query: str) -> dict:
    """Filtro de búsqueda por título: contiene el texto, sin distinguir mayúsculas.

    El dataset perdió los caracteres no ASCII: los reemplazó por `è` (A13). Buscar "Amélie"
    tiene que encontrar "Amèlie", así que la consulta se normaliza igual (contrato de
    ANOMALIAS, "texto"). Los datos no se tocan.
    """
    normalized = "".join(c if c.isascii() else "è" for c in query.strip())
    if not normalized:
        return {}
    # re.escape: lo que escribe el usuario es texto, no una expresión regular.
    return {"title": {"$regex": re.escape(normalized), "$options": "i"}}


def pipeline(query: str, page: int) -> list[dict]:
    """La página `page` (desde 1) del catálogo, de más a menos votada en IMDb."""
    return [
        {"$match": {**ACTIVE, **title_filter(query)}},
        {"$project": CARD_FIELDS},
        # Ordenar directo por imdb.votes pondría primero los votos en texto del crudo
        # ("1,208"): en Mongo los strings van después de los números, y en orden
        # descendente quedan arriba. Lo que no es número cuenta como null y va al final.
        {"$addFields": {"sortVotes": {"$cond": [{"$isNumber": "$imdb.votes"}, "$imdb.votes", None]}}},
        # _id desempata: sin un orden total, una película podría repetirse o faltar entre páginas.
        {"$sort": {"sortVotes": -1, "_id": 1}},
        {"$skip": (page - 1) * PAGE_SIZE},
        {"$limit": PAGE_SIZE},
    ]


async def list_movies(mongo: AsyncMongoClient, query: str, page: int) -> dict:
    """Lanza PyMongoError si Mongo no responde."""
    collection = mongo.get_default_database()[COLLECTION]
    total = await collection.count_documents({**ACTIVE, **title_filter(query)})
    cursor = await collection.aggregate(pipeline(query, page))
    documents = await cursor.to_list()
    return {
        "items": [to_card(d) for d in documents],
        "page": page,
        "pageSize": PAGE_SIZE,
        "total": total,
    }
