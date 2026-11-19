"""MongoDB con pymongo (I/O bloqueante).

MongoClient es thread-safe y se reconecta solo: si el servidor se cae y vuelve, las
operaciones siguientes vuelven a funcionar sin crear otro cliente. Por eso el latido
puede hacer el ping desde su propio hilo, con el mismo cliente que usa el servicio.

Política ante fallas (D14):
- Recuperable, se reintenta: el servidor no responde (ConnectionFailure).
- Irrecuperable, se propaga: credenciales rechazadas (OperationFailure).
"""

import logging
import time

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from dcicflix_common.config import MongoSettings

log = logging.getLogger(__name__)

# Con el default de pymongo (30 s), un ping a un Mongo caído tarda más que el latido.
_TIMEOUT_MS = 3000
_MAX_RETRY_DELAY = 10.0


def client(settings: MongoSettings) -> MongoClient:
    """Crea el cliente. No conecta todavía: pymongo conecta en la primera operación."""
    return MongoClient(
        settings.uri,
        serverSelectionTimeoutMS=_TIMEOUT_MS,
        connectTimeoutMS=_TIMEOUT_MS,
    )


def ping(mongo: MongoClient) -> None:
    """Lanza una excepción si Mongo no responde o rechaza las credenciales."""
    mongo.admin.command("ping")


def wait_until_ready(mongo: MongoClient, *, retry_for: float | None = None) -> None:
    """Espera a que Mongo responda, reintentando ante errores de conexión.

    retry_for: segundos máximos de reintento; None reintenta sin límite.
    """
    deadline = None if retry_for is None else time.monotonic() + retry_for
    delay = 1.0
    while True:
        try:
            ping(mongo)
        except ConnectionFailure as exc:
            if deadline is not None and time.monotonic() + delay > deadline:
                raise
            log.warning("MongoDB no disponible (%s); reintento en %.0f s", type(exc).__name__, delay)
            time.sleep(delay)
            delay = min(delay * 2, _MAX_RETRY_DELAY)
        else:
            log.info("conectado a MongoDB")
            return
