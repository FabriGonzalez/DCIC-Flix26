"""El ingest-consumer de punta a punta: de la cola a Mongo, sobre el sistema levantado."""

import json
import time

import pytest

import compose
import votes
from dcicflix_common import topology

pytestmark = pytest.mark.dynamic

TIMEOUT = 20


@pytest.fixture(scope="module", autouse=True)
def system():
    if not compose.containers():
        pytest.skip("no hay nada levantado: correr `docker compose up -d --wait`")


@pytest.fixture
def voter():
    voter = votes.Voter()
    yield voter
    voter.clean()


def wait_until_drained() -> None:
    """Espera a que la cola quede vacía: todo lo publicado ya tuvo su ack o su reject."""
    deadline = time.monotonic() + TIMEOUT
    # Al menos una vuelta: un mensaje recién publicado puede no figurar todavía.
    while True:
        time.sleep(1)
        if votes.is_drained():
            return
        if time.monotonic() > deadline:
            pytest.fail(f"a los {TIMEOUT} s la cola sigue así: {votes.queue()}")


def test_hay_un_solo_consumidor():
    # Con dos, los votos de un usuario se podrían procesar en paralelo y fuera de orden.
    assert votes.queue()["consumers"] == 1


def test_un_voto_publicado_queda_en_mongo(voter):
    voter.publish(rating=4)
    wait_until_drained()
    assert voter.saved() == [4]
    assert voter.added_to_count() == 1


def test_reentrega_cambio_y_voto_viejo(voter):
    voter.publish(rating=3, second=10)
    voter.publish(rating=3, second=10)  # el mismo, otra vez
    voter.publish(rating=5, second=20)  # cambia de opinión
    voter.publish(rating=1, second=5)  # uno viejo, que llega tarde
    wait_until_drained()
    assert voter.saved() == [5]
    assert voter.added_to_count() == 1


def test_un_mensaje_invalido_va_a_errores_y_no_frena_la_cola(voter):
    errors = topology.INTERACTIONS_ERRORS_QUEUE
    rows = {q["name"]: q["messages"] for q in compose.rabbitmqctl("list_queues", "name", "messages")}
    if rows[errors] != 0:
        pytest.skip(f"{errors} tiene mensajes; vaciarla con rabbitmqctl purge_queue {errors}")
    try:
        voter.publish(rating=9)
        voter.publish(rating=2)
        wait_until_drained()
        assert voter.saved() == [2]
        # Se mira el mensaje, no solo la cantidad: tiene que llegar intacto.
        code = (
            "import os, pika\n"
            "p = pika.ConnectionParameters(os.environ['RABBITMQ_HOST'], credentials=pika.PlainCredentials("
            "os.environ['RABBITMQ_USER'], os.environ['RABBITMQ_PASSWORD']))\n"
            "with pika.BlockingConnection(p) as c:\n"
            f"    print((c.channel().basic_get('{errors}')[2] or b'null').decode())\n"
        )
        assert json.loads(compose.exec_python("ingest-consumer", code).stdout) == voter.message(rating=9)
    finally:
        compose.run("exec", "-T", "rabbitmq", "rabbitmqctl", "-q", "purge_queue", errors, check=False)
