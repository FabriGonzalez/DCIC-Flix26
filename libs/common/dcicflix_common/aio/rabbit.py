"""RabbitMQ con aio-pika (asyncio).

`connect_robust` reconecta solo después de la primera conexión, pero no reintenta la
primera (comprobado en F4): si el broker no está, falla al instante. Por eso
`connect` reintenta la primera conexión con la misma política que sync/rabbit.py (D14):

- Recuperable, se reintenta: el broker todavía no está (AMQPConnectionError, OSError).
- Irrecuperable, se propaga: credenciales rechazadas o sin acceso al vhost, y
  topología faltante (TopologyError).

Los nombres de exchanges y colas salen de `topology.py`; acá no hay ninguno (D9).
"""

import asyncio
import logging
import time

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aiormq.exceptions import (
    AMQPConnectionError,
    AuthenticationError,
    ChannelNotFoundEntity,
    ConnectionNotAllowed,
    ProbableAuthenticationError,
)

from dcicflix_common import topology
from dcicflix_common.config import RabbitSettings
from dcicflix_common.errors import TopologyError

log = logging.getLogger(__name__)

# Subclases de AMQPConnectionError que no se arreglan reintentando.
_IRRECOVERABLE_CONNECTION_ERRORS = (AuthenticationError, ProbableAuthenticationError, ConnectionNotAllowed)

_MAX_RETRY_DELAY = 10.0

__all__ = ["TopologyError", "connect", "verify_topology"]


async def connect(
    settings: RabbitSettings, *, name: str | None = None, retry_for: float | None = None
) -> AbstractRobustConnection:
    """Conecta reintentando mientras el broker no esté disponible.

    name: nombre de la conexión, visible en `rabbitmqctl list_connections client_properties`.
    retry_for: segundos máximos de reintento; None reintenta sin límite.
    """
    deadline = None if retry_for is None else time.monotonic() + retry_for
    delay = 1.0
    while True:
        try:
            connection = await aio_pika.connect_robust(
                host=settings.host,
                port=settings.port,
                login=settings.user,
                password=settings.password,
                heartbeat=30,
                client_properties={"connection_name": name} if name else None,
            )
        except _IRRECOVERABLE_CONNECTION_ERRORS:
            raise
        except (AMQPConnectionError, OSError) as exc:
            if deadline is not None and time.monotonic() + delay > deadline:
                raise
            log.warning("RabbitMQ no disponible (%s: %s); reintento en %.0f s", type(exc).__name__, exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RETRY_DELAY)
        else:
            log.info("conectado a RabbitMQ en %s:%s", settings.host, settings.port)
            return connection


async def verify_topology(connection: AbstractRobustConnection) -> None:
    """Comprueba en forma pasiva (D10) que existan los exchanges y las colas.

    AMQP no permite consultar bindings: esos los comprueban los tests de arquitectura.
    """
    channel = await connection.channel()
    try:
        for exchange in topology.EXCHANGES:
            await channel.declare_exchange(exchange.name, passive=True)
        for queue in topology.QUEUES:
            await channel.declare_queue(queue.name, passive=True)
    except ChannelNotFoundEntity as exc:
        # Un declare pasivo de algo inexistente cierra el canal con 404 NOT_FOUND.
        raise TopologyError(f"falta la topología en el broker: {exc}") from exc
    finally:
        if not channel.is_closed:
            await channel.close()
