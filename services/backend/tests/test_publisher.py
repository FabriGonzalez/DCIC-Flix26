"""La publicación contra un RabbitMQ simulado: qué se manda y qué pasa cuando falla."""

import asyncio
import json
import time
from datetime import UTC, datetime

import aio_pika
import pytest
from aio_pika.exceptions import AMQPConnectionError, ChannelInvalidStateError, DeliveryError
from pamqp.commands import Basic

from app import publisher
from dcicflix_common.interactions import Interaction

VOTE = Interaction("usr_2001", "573a1399f29313caabceeb20", 5, "Muy buena", datetime(2026, 11, 25, 12, tzinfo=UTC))


class FakeRabbit:
    """Conexión, canal y exchange a la vez. `outcome`: lo que pasa al publicar."""

    def __init__(self, outcome=None, connected=True, hang_on_close=False):
        self.connected = asyncio.Event()
        if connected:
            self.connected.set()
        self.outcome = outcome
        self.hang_on_close = hang_on_close
        self.channel_options = []
        self.published = []
        self.open_channels = 0
        self.default_exchange = self

    def channel(self, **options):
        self.channel_options.append(options)
        return self

    async def __aenter__(self):
        self.open_channels += 1
        return self

    async def __aexit__(self, *exc):
        if self.hang_on_close:
            await asyncio.Event().wait()
        self.open_channels -= 1

    async def publish(self, message, routing_key, mandatory):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if self.outcome == "hang":
            await asyncio.Event().wait()
        self.published.append((message, routing_key, mandatory))


def run(make_rabbit, votes: int = 1) -> FakeRabbit:
    async def go():
        rabbit = make_rabbit()
        for _ in range(votes):
            await publisher.publish(rabbit, VOTE)
        return rabbit

    return asyncio.run(go())


def test_the_vote_goes_to_interactions_and_survives_a_restart():
    rabbit = run(FakeRabbit)
    [(message, routing_key, mandatory)] = rabbit.published
    assert routing_key == "interactions"
    assert json.loads(message.body)["user_id"] == "usr_2001"
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    # Sin estas tres, un voto perdido parecería publicado.
    assert mandatory
    assert rabbit.channel_options == [{"publisher_confirms": True, "on_return_raises": True}]


def test_each_vote_opens_and_closes_its_channel():
    rabbit = run(FakeRabbit, votes=3)
    assert len(rabbit.channel_options) == 3
    assert rabbit.open_channels == 0


@pytest.mark.parametrize("make_rabbit", [lambda: None, lambda: FakeRabbit(connected=False)])
def test_disconnected_fails_without_waiting(make_rabbit):
    started = time.monotonic()
    with pytest.raises(publisher.VoteNotPublished):
        run(make_rabbit)
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize(
    "error",
    [
        DeliveryError(None, Basic.Nack(delivery_tag=1)),  # nack, o sin cola (PublishError es subclase)
        AMQPConnectionError("se cortó"),
        ChannelInvalidStateError("canal cerrado"),
        ConnectionResetError(),
    ],
)
def test_rabbit_errors_mean_not_published(error):
    with pytest.raises(publisher.VoteNotPublished):
        run(lambda: FakeRabbit(error))


def test_a_bug_is_not_hidden():
    with pytest.raises(ZeroDivisionError):
        run(lambda: FakeRabbit(ZeroDivisionError()))


@pytest.mark.parametrize("hang_on_close", [False, True])
def test_hung_rabbit_gives_up_at_the_timeout(monkeypatch, hang_on_close):
    # Con wait_for, el caso de hang_on_close no terminaría nunca.
    monkeypatch.setattr(publisher, "TIMEOUT", 0.05)
    started = time.monotonic()
    with pytest.raises(publisher.VoteNotPublished):
        run(lambda: FakeRabbit("hang", hang_on_close=hang_on_close))
    assert time.monotonic() - started < 1
