"""Consume `interactions`: de a un mensaje, y responde recién cuando se sabe cómo salió.

    guardado, o ya había un voto más nuevo  → ack
    mensaje inválido                        → reject: pasa a interactions.errors
    error inesperado (un bug)               → reject, con el error en el log
    Mongo no responde                       → sin respuesta: se reintenta en la próxima vuelta
    Mongo rechaza la operación              → sin respuesta: el proceso termina (D14) y al
                                              reiniciar RabbitMQ entrega el mensaje de nuevo

El último caso no es culpa del mensaje (por ejemplo, credenciales cambiadas): si se
rechazara, todos los votos terminarían en interactions.errors.

El callback de pika solo anota el mensaje; lo procesa el tick. Así, mientras Mongo no
responde, el bucle del worker sigue atendiendo la conexión, la topología y el latido.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple

import pymongo
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError, WriteError

from dcicflix_common import topology
from dcicflix_common.errors import SubscriptionLostError
from dcicflix_common.interactions import InvalidInteraction, decode
from ingest import store

if TYPE_CHECKING:  # los tests unitarios corren sin pika
    import pika
    from pika.adapters.blocking_connection import BlockingChannel

log = logging.getLogger(__name__)

# Tope para guardar un voto. Sin él, un Mongo colgado (que acepta la conexión y no
# contesta) bloquearía el hilo que atiende a RabbitMQ.
SAVE_TIMEOUT = 10.0


class Delivery(NamedTuple):
    tag: int
    body: bytes


class Consumer:
    def __init__(self, db: Database):
        self._db = db
        self._channel: BlockingChannel | None = None
        # Con prefetch=1, RabbitMQ no entrega otro hasta que se responde este.
        self._pending: Delivery | None = None
        self._waiting_for_mongo = False

    def on_connect(self, connection: pika.BlockingConnection) -> None:
        """Se suscribe. Se llama en cada conexión."""
        # Un mensaje de la conexión anterior no se puede responder: RabbitMQ lo entrega de nuevo.
        self._pending = None
        channel = connection.channel()
        channel.basic_qos(prefetch_count=1)
        channel.add_on_cancel_callback(_on_cancel)
        channel.basic_consume(topology.INTERACTIONS_QUEUE, self._on_message)
        self._channel = channel
        log.info("suscripto a %s", topology.INTERACTIONS_QUEUE)

    def _on_message(self, _channel, method, _properties, body: bytes) -> None:
        self._pending = Delivery(method.delivery_tag, body)

    def tick(self, _connection: pika.BlockingConnection) -> None:
        if not self._channel.is_open:
            raise SubscriptionLostError("el broker cerró el canal")
        if self._pending is None:
            return

        try:
            accepted = self._process(self._pending.body)
        except PyMongoError as exc:
            if not _is_transient(exc):
                raise
            if not self._waiting_for_mongo:  # una vez por caída, no una por vuelta
                log.warning("Mongo no responde (%s); el voto espera y se reintenta", type(exc).__name__)
            self._waiting_for_mongo = True
            return

        if self._waiting_for_mongo:
            log.info("Mongo volvió a responder")
            self._waiting_for_mongo = False
        delivery, self._pending = self._pending, None
        if accepted:
            self._channel.basic_ack(delivery.tag)
        else:
            self._channel.basic_reject(delivery.tag, requeue=False)

    def _process(self, body: bytes) -> bool:
        """True si el mensaje quedó resuelto, False si hay que derivarlo a la cola de errores.

        Propaga los errores de Mongo que no dependen del mensaje.
        """
        try:
            vote = decode(body)
            with pymongo.timeout(SAVE_TIMEOUT):
                saved = store.save(self._db, vote)
        except InvalidInteraction as exc:
            log.warning("mensaje inválido, va a %s: %s", topology.INTERACTIONS_ERRORS_QUEUE, exc)
            return False
        except Exception as exc:
            if _is_transient(exc) or _is_rejected_by_server(exc):
                raise
            log.exception("error inesperado, el mensaje va a %s", topology.INTERACTIONS_ERRORS_QUEUE)
            return False

        outcome = "guardado" if saved else "ignorado: ya había uno más nuevo"
        log.info("voto de %s a %s: %s", vote.user_id, vote.movie_id, outcome)
        return True


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, ConnectionFailure) or (isinstance(exc, PyMongoError) and exc.timeout)


def _is_rejected_by_server(exc: Exception) -> bool:
    # WriteError es la excepción: lo rechazado es ese documento, no la operación.
    return isinstance(exc, OperationFailure) and not isinstance(exc, WriteError)


def _on_cancel(_method) -> None:
    raise SubscriptionLostError(f"el broker canceló la suscripción a {topology.INTERACTIONS_QUEUE}")
