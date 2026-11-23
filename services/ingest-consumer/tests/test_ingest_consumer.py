"""Qué se le responde a RabbitMQ según cómo salió, con un canal y un guardado de mentira."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("pymongo")
from pymongo.errors import (  # noqa: E402
    AutoReconnect,
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
    WriteError,
)

from dcicflix_common import topology  # noqa: E402
from dcicflix_common.errors import SubscriptionLostError  # noqa: E402
from dcicflix_common.interactions import Interaction, InvalidInteraction, encode  # noqa: E402
from ingest import store  # noqa: E402
from ingest.consumer import Consumer  # noqa: E402

VOTE = Interaction("usr_0001", "573a1393f29313caabcdd7d8", 5, "Muy buena", datetime(2026, 11, 23, tzinfo=UTC))


class FakeChannel:
    def __init__(self):
        self.is_open = True
        self.prefetch = self.queue = self.on_message = self.on_cancel = None
        self.answers = []

    def basic_qos(self, prefetch_count):
        self.prefetch = prefetch_count

    def add_on_cancel_callback(self, callback):
        self.on_cancel = callback

    def basic_consume(self, queue, on_message_callback):
        self.queue, self.on_message = queue, on_message_callback

    def basic_ack(self, tag):
        self.answers.append(("ack", tag))

    def basic_reject(self, tag, requeue):
        self.answers.append(("reject", tag, requeue))

    def deliver(self, tag=1, body=None):
        self.on_message(self, SimpleNamespace(delivery_tag=tag), None, encode(VOTE) if body is None else body)


class Saves:
    """Reemplaza a store.save: cada llamada usa el siguiente resultado (o lo lanza)."""

    def __init__(self, monkeypatch):
        self.results, self.votes = [], []
        monkeypatch.setattr(store, "save", self)

    def __call__(self, _db, vote):
        self.votes.append(vote)
        result = self.results.pop(0) if self.results else True
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def saves(monkeypatch):
    return Saves(monkeypatch)


@pytest.fixture
def consumer():
    return Consumer(db=None)


def connect(consumer) -> FakeChannel:
    channel = FakeChannel()
    consumer.on_connect(SimpleNamespace(channel=lambda: channel))
    return channel


def test_se_suscribe_de_a_un_mensaje(consumer):
    channel = connect(consumer)
    assert (channel.queue, channel.prefetch) == (topology.INTERACTIONS_QUEUE, 1)


def test_sin_mensajes_no_hace_nada(consumer, saves):
    channel = connect(consumer)
    consumer.tick(None)
    assert (saves.votes, channel.answers) == ([], [])


@pytest.mark.parametrize("saved", [True, False], ids=["guardado", "habia-uno-mas-nuevo"])
def test_confirma_despues_de_guardar(consumer, saves, saved):
    channel = connect(consumer)
    saves.results = [saved]
    channel.deliver(tag=7)
    assert channel.answers == []  # recibir no es confirmar
    consumer.tick(None)
    assert saves.votes == [VOTE]
    assert channel.answers == [("ack", 7)]
    consumer.tick(None)
    assert channel.answers == [("ack", 7)]  # una sola respuesta


def test_mensaje_ilegible_a_la_cola_de_errores(consumer, saves):
    channel = connect(consumer)
    channel.deliver(body=b"{")
    consumer.tick(None)
    assert saves.votes == []
    assert channel.answers == [("reject", 1, False)]


@pytest.mark.parametrize(
    "error",
    [InvalidInteraction("movie_id"), KeyError("bug"), WriteError("documento rechazado", 121)],
    ids=["pelicula-inexistente", "bug", "documento-rechazado"],
)
def test_falla_del_mensaje_a_la_cola_de_errores_y_sigue(consumer, saves, error):
    channel = connect(consumer)
    saves.results = [error]
    channel.deliver(tag=1)
    consumer.tick(None)
    channel.deliver(tag=2)
    consumer.tick(None)
    assert channel.answers == [("reject", 1, False), ("ack", 2)]


@pytest.mark.parametrize(
    "error",
    [
        AutoReconnect("x"),
        NetworkTimeout("x"),
        ServerSelectionTimeoutError("x"),
        ExecutionTimeout("x", 50),
    ],
    ids=lambda e: type(e).__name__,
)
def test_mongo_caido_reintenta_sin_responder(consumer, saves, error):
    channel = connect(consumer)
    saves.results = [error, error, True]
    channel.deliver(tag=7)
    consumer.tick(None)
    consumer.tick(None)
    assert channel.answers == []
    consumer.tick(None)
    assert channel.answers == [("ack", 7)]
    assert saves.votes == [VOTE] * 3


def test_mongo_rechaza_la_operacion_termina_sin_responder(consumer, saves):
    channel = connect(consumer)
    saves.results = [OperationFailure("Authentication failed", 18)]
    channel.deliver()
    with pytest.raises(OperationFailure):
        consumer.tick(None)
    assert channel.answers == []


def test_al_reconectar_olvida_el_mensaje_de_la_conexion_anterior(consumer, saves):
    old = connect(consumer)
    old.deliver(tag=7)
    new = connect(consumer)
    consumer.tick(None)
    assert (saves.votes, old.answers, new.answers) == ([], [], [])
    new.deliver(tag=1)  # RabbitMQ lo entrega de nuevo, con otro tag
    consumer.tick(None)
    assert (old.answers, new.answers) == ([], [("ack", 1)])


def test_termina_si_el_broker_cancela_la_suscripcion(consumer):
    with pytest.raises(SubscriptionLostError):
        connect(consumer).on_cancel(None)


def test_termina_si_el_broker_cierra_el_canal(consumer, saves):
    channel = connect(consumer)
    channel.is_open = False
    with pytest.raises(SubscriptionLostError):
        consumer.tick(None)
