"""Publica un voto en la cola `interactions`.

Vuelve cuando RabbitMQ confirma que lo recibió: desde ahí el voto no se pierde. Que el
ingest-consumer lo guarde en MongoDB pasa después, y no lo espera nadie.

    confirmado por RabbitMQ                       → vuelve
    desconectado, rechazado, cola inexistente     → VoteNotPublished, al instante
    RabbitMQ no contesta                          → VoteNotPublished, a los TIMEOUT segundos

En el último caso (o si la conexión se corta esperando) el voto pudo haber llegado igual.
Votar de nuevo es seguro: el consumer reemplaza el voto anterior del usuario.
"""

import asyncio
import logging

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import AMQPError, ChannelInvalidStateError

from dcicflix_common import topology
from dcicflix_common.interactions import Interaction, encode

# Lo normal son unos milisegundos. Solo se llega al tope con un RabbitMQ colgado.
TIMEOUT = 2.0

log = logging.getLogger(__name__)

# Publicaciones vencidas que todavía se están cerrando: asyncio no guarda las tareas sueltas.
_closing: set[asyncio.Task] = set()


class VoteNotPublished(Exception):
    """RabbitMQ no confirmó el voto."""


async def publish(rabbit: AbstractRobustConnection | None, vote: Interaction) -> None:
    """Lanza VoteNotPublished si RabbitMQ no confirma el voto."""
    # Sin esto, una conexión caída esperaría a reconectar hasta el tope.
    if rabbit is None or not rabbit.connected.is_set():
        raise VoteNotPublished("sin conexión con RabbitMQ")

    task = asyncio.create_task(_publish(rabbit, encode(vote)))
    # wait y no wait_for: con RabbitMQ colgado, cerrar el canal también se cuelga, y
    # wait_for esperaría a que la tarea cancelada termine de cerrarlo.
    await asyncio.wait({task}, timeout=TIMEOUT)
    if not task.done():
        _cancel(task)
        raise VoteNotPublished(f"RabbitMQ no contestó en {TIMEOUT:.0f} s")
    try:
        task.result()
    except (AMQPError, ChannelInvalidStateError, OSError) as exc:
        raise VoteNotPublished(f"{type(exc).__name__}: {exc}") from exc


async def _publish(rabbit: AbstractRobustConnection, body: bytes) -> None:
    # Un canal por voto: si se rompe, el siguiente no se entera y no hay nada que reabrir.
    # on_return_raises: sin él, publicar en una cola que no existe parece un éxito.
    async with rabbit.channel(publisher_confirms=True, on_return_raises=True) as channel:
        message = aio_pika.Message(
            body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # sobrevive a un reinicio de RabbitMQ
        )
        await channel.default_exchange.publish(message, routing_key=topology.INTERACTIONS_QUEUE, mandatory=True)


def _cancel(task: asyncio.Task) -> None:
    """Cancela sin esperar. Cancelada, la publicación no se reintenta al reconectar."""
    task.cancel()
    _closing.add(task)
    task.add_done_callback(_closed)


def _closed(task: asyncio.Task) -> None:
    _closing.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.debug("publicación vencida: %r", task.exception())
