"""Coherencia interna de topology.py, sin broker."""

from dcicflix_common import topology

EXCHANGE_NAMES = {e.name for e in topology.EXCHANGES}
QUEUE_NAMES = {q.name for q in topology.QUEUES}


def test_nombres_unicos():
    assert len(EXCHANGE_NAMES) == len(topology.EXCHANGES)
    assert len(QUEUE_NAMES) == len(topology.QUEUES)


def test_bindings_apuntan_a_lo_declarado():
    for binding in topology.BINDINGS:
        assert binding.exchange in EXCHANGE_NAMES, binding
        assert binding.queue in QUEUE_NAMES, binding


def test_dead_letter_exchanges_declarados():
    for queue in topology.QUEUES:
        dlx = queue.arguments.get("x-dead-letter-exchange")
        if dlx is not None:
            assert dlx in EXCHANGE_NAMES, f"{queue.name} deriva a {dlx}, que no está declarado"


def test_todo_es_durable():
    # README: los votos y la señal de datos limpios no se pueden perder.
    assert all(e.durable for e in topology.EXCHANGES)
    assert all(q.durable for q in topology.QUEUES)
