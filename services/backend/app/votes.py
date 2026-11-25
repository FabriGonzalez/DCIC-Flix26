"""Votar una película: POST /movies/{id}/reviews (README, "Voto con reseña").

    formato           → 422 (404 si el id de la película no es válido)
    estado            → 409 si no es "ready"
    usuario, película → 404 si no existen o la película no está activa
    publicar          → 503 si RabbitMQ no confirma
    aceptado          → 202

Se comprueba acá todo lo que depende de quien vota: después del 202 no hay forma de avisarle.
Comprobar son lecturas por _id; lo lento, que es guardar, lo hace el ingest-consumer.

409 y no 503 para el estado: el frontend lo distingue de una caída y vuelve a consultar /status.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import AsyncMongoClient

from dcicflix_common.interactions import Interaction, InvalidInteraction

from app import catalog, publisher, status, users

# El criterio del ingest-consumer. Con $ne, como en el catálogo, pasaría un documento crudo.
_ACTIVE = {"deleted": False}

Publish = Callable[[Interaction], Awaitable[None]]


class Rejected(Exception):
    """El voto no se acepta. `status_code` es el código HTTP."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def build(movie_id: str, body: Any) -> Interaction:
    """El voto, con la hora de ahora. Lanza Rejected si el formato no es válido."""
    if not ObjectId.is_valid(movie_id):
        raise Rejected(404, "no existe la película")
    if not isinstance(body, dict):
        raise Rejected(422, "el cuerpo no es un objeto JSON")
    try:
        return Interaction(
            user_id=body.get("userId"),
            movie_id=str(ObjectId(movie_id)),  # en minúscula, como lo pide el mensaje
            rating=body.get("rating"),
            comment=body.get("comment", ""),
            voted_at=datetime.now(UTC),
        )
    except InvalidInteraction as exc:
        raise Rejected(422, str(exc)) from exc


async def submit(
    mongo: AsyncMongoClient, vote: Interaction, *, recommender_ready: bool, users_loaded: bool, publish: Publish
) -> None:
    """Comprueba y publica. Lanza Rejected, o PyMongoError si Mongo no responde."""
    if status.combine(await status.read_mark(mongo), recommender_ready) != status.READY:
        raise Rejected(409, "los votos se habilitan cuando el sistema está listo")
    await _check_user(mongo, vote.user_id, users_loaded)
    await _check_movie(mongo, vote.movie_id)
    try:
        await publish(vote)
    except publisher.VoteNotPublished as exc:
        raise Rejected(503, "no se pudo enviar el voto") from exc


def to_response(vote: Interaction) -> dict:
    return {
        "movieId": vote.movie_id,
        "userId": vote.user_id,
        "rating": vote.rating,
        "comment": vote.comment,
        "votedAt": vote.voted_at.isoformat(),
    }


async def _check_user(mongo: AsyncMongoClient, user_id: str, users_loaded: bool) -> None:
    if await mongo.get_default_database()[users.COLLECTION].find_one({"_id": user_id}, {"_id": 1}) is not None:
        return
    if not users_loaded:
        # Decir que no existe sería inventarlo: puede ser uno de los que faltan cargar.
        raise Rejected(503, "los usuarios se están cargando")
    raise Rejected(404, "no existe el usuario")


async def _check_movie(mongo: AsyncMongoClient, movie_id: str) -> None:
    movies = mongo.get_default_database()[catalog.COLLECTION]
    if await movies.find_one({"_id": ObjectId(movie_id), **_ACTIVE}, {"_id": 1}) is None:
        raise Rejected(404, "no existe la película")
