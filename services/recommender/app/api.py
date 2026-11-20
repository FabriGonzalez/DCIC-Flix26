"""API para el backend (docs/recomendador.md 9.4). Solo HTTP interno: el recommender vive
en internal-net sin puerto publicado, y el frontend le pide todo al backend.

Devuelve identificadores (`movie_id` = _id como string hexadecimal); la ficha la completa
el backend desde MongoDB.

    GET /users/{user_id}/recommendations?limit=20   {source, items: [{movie_id, score, because}]}
    GET /movies/{movie_id}/similar?limit=10         {items: [{movie_id, score}]}       404 si no está activa
    GET /rankings?genre=&limit=20                   {genre, items: [{movie_id, wr}]}   404 si el género no existe
    GET /genres                                     {items: [{genre, movies}]}

- Sin índice (embebiendo, esperando la limpieza o indexando por primera vez): 503 con
  {detail, phase}. Al reindexar se sigue respondiendo con el índice anterior.
- `limit` fuera de 1–100: 422 (validación de FastAPI).
- Cada petición toma `recommender.index` una sola vez: catálogo y calidad del mismo momento,
  aunque el WR se recalcule o se reindexe en el medio.
- Regla del event loop: for_user y similar (≈ 5–12 ms) van en un hilo; los rankings y
  los géneros solo leen listas ya calculadas.
"""

import asyncio

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app import store
from app.lifecycle import Index, Recommender
from app.recommend import Item, for_user, ranking, similar

LIMIT_MAX = 100
RETRY_AFTER = "5"  # segundos: el indexado tarda ≈ 17 s, el primer embedding ≈ 8 min


class NotReady(Exception):
    def __init__(self, phase: str):
        self.phase = phase


def install(app: FastAPI, recommender: Recommender) -> None:
    app.include_router(_router(recommender))

    @app.exception_handler(NotReady)
    async def not_ready(request: Request, exc: NotReady) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "el recomendador todavía no tiene índice", "phase": exc.phase},
            headers={"Retry-After": RETRY_AFTER},
        )


def _router(recommender: Recommender) -> APIRouter:
    api = APIRouter()

    def current() -> Index:
        index = recommender.index
        if index is None:
            raise NotReady(recommender.phase)
        return index

    @api.get("/users/{user_id}/recommendations")
    async def recommendations(user_id: str, limit: int = Query(20, ge=1, le=LIMIT_MAX)) -> dict:
        index = current()
        try:
            votes = await store.read_user_votes(recommender.db, user_id, index.catalog)
        except PyMongoError as exc:
            raise HTTPException(503, "MongoDB no disponible") from exc
        source, items = await asyncio.to_thread(for_user, index.catalog, index.quality, votes, limit)
        ids = index.catalog.ids
        return {
            "source": source,
            "items": [
                {**_scored(ids, item), "because": None if item.because is None else ids[item.because]}
                for item in items
            ],
        }

    @api.get("/movies/{movie_id}/similar")
    async def similar_movies(movie_id: str, limit: int = Query(10, ge=1, le=LIMIT_MAX)) -> dict:
        index = current()
        row = index.catalog.rows.get(movie_id)
        if row is None:
            raise HTTPException(404, "la película no está activa")
        items = await asyncio.to_thread(similar, index.catalog, index.quality, row, limit)
        return {"items": [_scored(index.catalog.ids, item) for item in items]}

    @api.get("/rankings")
    async def rankings(genre: str | None = None, limit: int = Query(20, ge=1, le=LIMIT_MAX)) -> dict:
        index = current()
        if genre is not None and genre not in index.quality.by_genre:
            raise HTTPException(404, "el género no existe")
        ids = index.catalog.ids
        items = ranking(index.quality, limit, genre=genre)
        return {"genre": genre, "items": [{"movie_id": ids[item.row], "wr": round(item.score, 4)} for item in items]}

    @api.get("/genres")
    async def genres() -> dict:
        counts = current().catalog.genre_counts()
        ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        return {"items": [{"genre": genre, "movies": movies} for genre, movies in ordered]}

    return api


def _scored(ids: list[str], item: Item) -> dict:
    return {"movie_id": ids[item.row], "score": round(item.score, 4)}
