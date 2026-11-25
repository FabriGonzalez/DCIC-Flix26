"""Usuarios: la carga de la colección `users` y GET /users (README, "Usuarios").

    {_id: "usr_0142", name, email, preloaded}      _id es el user_id de reviews

No hay registro: se elige uno de la lista. Son los 2.000 del dataset, cuyos datos solo están
repetidos en cada reseña, y unos pocos nuevos (PRELOADED) sin ningún voto, para probar el
arranque en frío del recomendador.

La carga corre en cada arranque del backend. Es idempotente: agrega los que faltan y no toca
los que están, así que también completa una carga cortada a la mitad.

No espera a la limpieza: en el crudo cada user_id tiene un solo nombre y un solo email, y lo
único que descarta la limpieza son las reseñas anónimas, que acá se filtran por id.
"""

import asyncio
import logging
import re
from collections.abc import Callable

from pymongo import AsyncMongoClient, UpdateOne
from pymongo.errors import PyMongoError

from dcicflix_common.interactions import ANONYMOUS_ID

COLLECTION = "users"
REVIEWS = "reviews"
LIMIT = 20
_RETRY_DELAY = 5.0

# Los ids siguen a los del dataset (usr_0001 a usr_2000). El dominio .test está reservado
# (RFC 2606): ningún email es de alguien.
PRELOADED = [
    {"_id": f"usr_{number}", "name": name, "email": f"{name.split()[0].lower()}@dcicflix.test", "preloaded": True}
    for number, name in enumerate(
        ("Ana Torres", "Bruno Medina", "Carla Sosa", "Diego Funes", "Elena Vidal"), start=2001
    )
]

log = logging.getLogger(__name__)


def load_pipeline() -> list[dict]:
    """Los usuarios del dataset, de `reviews` a `users`. Corre entero dentro de Mongo."""
    return [
        {
            "$match": {
                "user_id": {"$type": "string", "$nin": ["", ANONYMOUS_ID]},
                # Las reseñas que crea el ingest-consumer no tienen nombre ni email.
                "user_name": {"$type": "string"},
            }
        },
        {"$group": {"_id": "$user_id", "name": {"$first": "$user_name"}, "email": {"$first": "$user_email"}}},
        {"$set": {"preloaded": False}},
        {"$merge": {"into": COLLECTION, "on": "_id", "whenMatched": "keepExisting", "whenNotMatched": "insert"}},
    ]


async def load(mongo: AsyncMongoClient) -> int:
    """Agrega los usuarios que falten y devuelve cuántos hay. Lanza PyMongoError si Mongo no responde."""
    db = mongo.get_default_database()
    await db[REVIEWS].aggregate(load_pipeline())
    await db[COLLECTION].bulk_write(
        [UpdateOne({"_id": user["_id"]}, {"$setOnInsert": user}, upsert=True) for user in PRELOADED]
    )
    return await db[COLLECTION].count_documents({})


def search_filter(query: str) -> dict:
    """Contiene el texto en el nombre, el email o el id, sin distinguir mayúsculas."""
    text = query.strip()
    if not text:
        return {}
    # re.escape: lo que escribe el usuario es texto, no una expresión regular.
    condition = {"$regex": re.escape(text), "$options": "i"}
    return {"$or": [{"name": condition}, {"email": condition}, {"_id": condition}]}


async def list_users(mongo: AsyncMongoClient, query: str) -> dict:
    """Los primeros LIMIT que coinciden: los nuevos adelante y después por nombre.

    El email sirve para buscar, pero no se devuelve. Los nombres se repiten: lo que
    distingue a dos usuarios es el id.
    """
    collection = mongo.get_default_database()[COLLECTION]
    matching = search_filter(query)
    total = await collection.count_documents(matching)
    cursor = collection.find(matching, {"name": 1, "preloaded": 1})
    documents = await cursor.sort([("preloaded", -1), ("name", 1), ("_id", 1)]).limit(LIMIT).to_list()
    return {
        "items": [{"id": d["_id"], "name": d["name"], "preloaded": d["preloaded"]} for d in documents],
        "total": total,
    }


class UserLoader:
    """Carga los usuarios en segundo plano, reintentando mientras Mongo no responda.

    Hasta que termina, `loaded` es False y GET /users responde 503: una lista a medio cargar
    parecería completa. El resto del backend no espera.
    """

    def __init__(self, mongo: AsyncMongoClient, *, on_fatal: Callable[[BaseException], None]):
        self._mongo = mongo
        self._on_fatal = on_fatal
        self._task: asyncio.Task | None = None
        self.loaded = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="load-users")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        try:
            await self._load_with_retries()
        except Exception as exc:  # un bug: reintentar no lo arregla (D14)
            self._on_fatal(exc)

    async def _load_with_retries(self) -> None:
        while True:
            try:
                total = await load(self._mongo)
            except PyMongoError as exc:
                log.warning("no pude cargar los usuarios (%s); reintento en %.0f s", type(exc).__name__, _RETRY_DELAY)
                await asyncio.sleep(_RETRY_DELAY)
            else:
                self.loaded = True
                log.info("usuarios cargados: %d", total)
                return
