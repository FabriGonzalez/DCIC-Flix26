"""Estado del sistema para el frontend: GET /status (README, "Estado del sistema").

    marca de limpieza ≠ done              → cleaning
    marca done, recommender no listo      → indexing
    marca done, recommender listo         → ready

La marca se lee de Mongo en cada pedido (un find_one por _id). Si el recommender está
listo lo anota el monitor de salud cada 10 s (RecommenderProbe): así el costo de /status
no depende de cuántos navegadores consulten, igual que /health (D12).
"""

import httpx
from pymongo import AsyncMongoClient

from dcicflix_common import cleaning

CLEANING = "cleaning"
INDEXING = "indexing"
READY = "ready"


def combine(mark: str | None, recommender_ready: bool) -> str:
    """El estado a partir de la marca (None si no hay documento) y del recommender."""
    if mark != cleaning.DONE:
        return CLEANING
    return READY if recommender_ready else INDEXING


async def read_mark(mongo: AsyncMongoClient) -> str | None:
    """Lee la marca de limpieza. Lanza PyMongoError si Mongo no responde."""
    collection = mongo.get_default_database()[cleaning.COLLECTION]
    document = await collection.find_one({"_id": cleaning.DOCUMENT_ID}, {cleaning.STATUS_FIELD: 1})
    return None if document is None else document.get(cleaning.STATUS_FIELD)


class RecommenderProbe:
    """Check informativo del monitor que además anota si el recommender está listo.

    El /health del recommender da 200 aunque todavía esté embebiendo o indexando: "sano"
    no es "listo". Lo que dice si está listo es el campo "ready" del cuerpo.
    """

    def __init__(self, http: httpx.AsyncClient, url: str):
        self._http = http
        self._url = url
        self.ready = False

    async def check(self) -> None:
        # Si el pedido falla, queda en False: un recommender que no responde no está listo.
        # Cambia una sola vez, al final: mientras pregunta vale la respuesta anterior.
        ready = False
        try:
            response = await self._http.get(f"{self._url}/health")
            response.raise_for_status()  # 503: el recommender responde, pero no está sano
            ready = response.json().get("ready") is True
        finally:
            self.ready = ready
