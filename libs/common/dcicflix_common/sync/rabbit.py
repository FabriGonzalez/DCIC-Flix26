"""RabbitMQ con pika (I/O bloqueante).

Política ante fallas (D14):
- Recuperable, se reintenta: el broker todavía no está o se cortó la conexión.
- Irrecuperable, se propaga: credenciales rechazadas, canal cerrado por el broker
  (por ejemplo PRECONDITION_FAILED) o topología faltante. El proceso termina y,
  si es un servicio de larga vida, `restart: unless-stopped` lo vuelve a levantar.

Los nombres de exchanges y colas salen de `topology.py`; acá no hay ninguno (D9).
"""

import logging
import time

import pika
from pika.exceptions import (
    AMQPConnectionError,
    AuthenticationError,
    ChannelClosedByBroker,
    ProbableAccessDeniedError,
    ProbableAuthenticationError,
)

from dcicflix_common import topology
from dcicflix_common.config import RabbitSettings

log = logging.getLogger(__name__)

# Subclases de AMQPConnectionError que no se arreglan reintentando.
_IRRECOVERABLE_CONNECTION_ERRORS = (
    AuthenticationError,
    ProbableAuthenticationError,
    ProbableAccessDeniedError,
)

_MAX_RETRY_DELAY = 10.0


class TopologyError(RuntimeError):
    """El broker no tiene la topología de topology.py."""


def connect(settings: RabbitSettings, *, retry_for: float | None = None) -> pika.BlockingConnection:
    """Conecta reintentando mientras el broker no esté disponible.

    retry_for: segundos máximos de reintento; None reintenta sin límite.
    """
    parameters = pika.ConnectionParameters(
        host=settings.host,
        port=settings.port,
        credentials=pika.PlainCredentials(settings.user, settings.password),
        heartbeat=30,
        connection_attempts=1,
    )
    deadline = None if retry_for is None else time.monotonic() + retry_for
    delay = 1.0
    while True:
        try:
            connection = pika.BlockingConnection(parameters)
        except _IRRECOVERABLE_CONNECTION_ERRORS:
            raise
        # OSError: con el contenedor de rabbitmq detenido, su nombre deja de resolver
        # y pika lanza socket.gaierror, que no es un AMQPConnectionError.
        except (AMQPConnectionError, OSError) as exc:
            if deadline is not None and time.monotonic() + delay > deadline:
                raise
            log.warning("RabbitMQ no disponible (%s: %s); reintento en %.0f s", type(exc).__name__, exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, _MAX_RETRY_DELAY)
        else:
            log.info("conectado a RabbitMQ en %s:%s", settings.host, settings.port)
            return connection


def declare_topology(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """Declara exchanges, colas y bindings. Idempotente si ya existen iguales."""
    for exchange in topology.EXCHANGES:
        channel.exchange_declare(exchange=exchange.name, exchange_type=exchange.type, durable=exchange.durable)
    for queue in topology.QUEUES:
        channel.queue_declare(queue=queue.name, durable=queue.durable, arguments=queue.arguments)
    for binding in topology.BINDINGS:
        channel.queue_bind(queue=binding.queue, exchange=binding.exchange, routing_key=binding.routing_key)


def verify_topology(connection: pika.BlockingConnection) -> None:
    """Comprueba en forma pasiva (D10) que existan los exchanges y las colas.

    AMQP no permite consultar bindings: esos los comprueban los tests de arquitectura.
    """
    channel = connection.channel()
    try:
        for exchange in topology.EXCHANGES:
            channel.exchange_declare(exchange=exchange.name, passive=True)
        for queue in topology.QUEUES:
            channel.queue_declare(queue=queue.name, passive=True)
    except ChannelClosedByBroker as exc:
        # Un declare pasivo de algo inexistente cierra el canal con 404 NOT_FOUND.
        raise TopologyError(f"falta la topología en el broker: {exc.reply_text}") from exc
    channel.close()
