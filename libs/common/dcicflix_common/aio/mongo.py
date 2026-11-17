"""MongoDB con AsyncMongoClient (pymongo, asyncio).

Misma política que sync/mongo.py (D14): reintenta si el servidor no responde
(ConnectionFailure) y propaga las credenciales rechazadas (OperationFailure).
El cliente se reconecta solo si el servidor se cae y vuelve.
"""

import asyncio
import logging
import time

from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure

from dcicflix_common.config import MongoSettings

log = logging.getLogger(__name__)

# Con el default de pymongo (30 s), un ping a un Mongo caído tarda más que el monitor.
_TIMEOUT_MS = 3000
_MAX_RETRY_DELAY = 10.0


def client(settings: MongoSettings) -> AsyncMongoClient:
    """Crea el cliente. No conecta todavía: pymongo conecta en la primera operación."""
    return AsyncMongoClient(
        settings.uri,
        serverSelectionTimeoutMS=_TIMEOUT_MS,
        connectTimeoutMS=_TIMEOUT_MS,
    )


async def ping(mongo: AsyncMongoClient) -> None:
    """Lanza una excepción si Mongo no responde o rechaza las credenciales."""
    await mongo.admin.command("ping")


async def wait_until_ready(mongo: AsyncMongoClient, *, retry_for: float | None = None) -> None:
    """Espera a que Mongo responda, reintentando ante errores de conexión.

    retry_for: segundos máximos de reintento; None reintenta sin límite.
    """
    deadline = None if retry_for is None else time.monotonic() + retry_for
    delay = 1.0
    while True:
        try:
            await ping(mongo)
        except ConnectionFailure as exc:
            if deadline is not None and time.monotonic() + delay > deadline:
                raise
            log.warning("MongoDB no disponible (%s); reintento en %.0f s", type(exc).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RETRY_DELAY)
        else:
            log.info("conectado a MongoDB")
            return
