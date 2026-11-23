"""Guarda un voto con reseña en MongoDB.

RabbitMQ entrega cada mensaje al menos una vez: si el proceso se cae entre guardar y
confirmar, el voto llega de nuevo. Por eso guardar dos veces el mismo voto deja la base
igual que guardarlo una.

No reintenta ni captura fallas de conexión: qué hacer con ellas lo decide quien llama.
"""

from bson import ObjectId
from pymongo import ASCENDING, WriteConcern
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from dcicflix_common.interactions import Interaction, InvalidInteraction

# j: Mongo responde con la escritura ya en el journal, en disco. Sin esto, un corte podría
# perder un voto que ya se le confirmó a RabbitMQ.
_DURABLE = WriteConcern(w=1, j=True)

_ACTIVE = {"deleted": False}


def ensure_indexes(db: Database) -> None:
    """Un solo voto activo por usuario y película (ANOMALIAS, sección 7). Idempotente.

    Es parcial porque los votos descartados por la limpieza sí se repiten. Se puede crear
    antes de la limpieza: los documentos crudos no tienen `deleted` y quedan afuera.
    """
    db.reviews.create_index(
        [("user_id", ASCENDING), ("movie_id", ASCENDING)],
        name="one_active_vote",
        unique=True,
        partialFilterExpression=_ACTIVE,
    )


def save(db: Database, vote: Interaction) -> bool:
    """Guarda el voto y actualiza el contador de la película.

    Devuelve False si ya había un voto más nuevo, que queda como está.
    Lanza InvalidInteraction si la película no existe o no está activa.
    """
    movie_id = ObjectId(vote.movie_id)
    if db.movies.find_one({"_id": movie_id, **_ACTIVE}, {"_id": 1}) is None:
        raise InvalidInteraction(f"movie_id: {movie_id} no es una película activa")

    saved = _save_review(db, vote, movie_id)
    # También si no se guardó nada: una entrega anterior pudo caerse antes de este paso.
    _update_comment_count(db, movie_id)
    return saved


def _save_review(db: Database, vote: Interaction, movie_id: ObjectId) -> bool:
    """Actualiza el voto activo del usuario para la película, o lo crea, en una sola operación.

    El filtro pide que el voto guardado no sea más nuevo (una fecha desconocida, null, se
    reemplaza). Si es más nuevo, el filtro no encuentra nada, el upsert intenta crear otro
    voto activo y el índice único lo impide.
    """
    reviews = db.reviews.with_options(write_concern=_DURABLE)
    key = {"user_id": vote.user_id, "movie_id": movie_id, **_ACTIVE}
    not_newer = {"$or": [{"date": None}, {"date": {"$lte": vote.voted_at}}]}
    fields = {
        "rating": vote.rating,
        "comment": vote.comment,
        "date": vote.voted_at,
        "datePrecision": "day",
        "deletedReason": None,
        "commentHidden": not vote.comment.strip(),
    }
    try:
        # Al crear, Mongo agrega también las igualdades del filtro: user_id, movie_id y deleted.
        reviews.update_one({**key, **not_newer}, {"$set": fields}, upsert=True)
    except DuplicateKeyError:
        return False
    return True


def _update_comment_count(db: Database, movie_id: ObjectId) -> None:
    """num_mflix_comments = reseñas visibles, con el criterio del cleaning-agent (A16).

    Se recuenta en lugar de sumar 1: sumar contaría dos veces un voto reentregado.
    """
    visible = db.reviews.count_documents({"movie_id": movie_id, **_ACTIVE, "commentHidden": False})
    movies = db.movies.with_options(write_concern=_DURABLE)
    movies.update_one({"_id": movie_id}, {"$set": {"num_mflix_comments": visible}})
