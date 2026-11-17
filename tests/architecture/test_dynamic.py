"""Verificaciones sobre el sistema levantado: docker compose up -d --wait"""

import json

import pytest

import compose
import spec
from dcicflix_common import topology

pytestmark = pytest.mark.dynamic

SERVICES = sorted(compose.services())


@pytest.fixture(scope="module")
def containers():
    found = compose.containers()
    if not found:
        pytest.skip("no hay nada levantado: correr `docker compose up -d --wait`")
    return found


@pytest.mark.parametrize("service", SERVICES)
def test_servicio_sano(service, containers):
    """Criterio 1: todo healthy, y los servicios de una sola vez en Exited (0)."""
    assert service in containers, f"{service} no tiene contenedor"
    c = containers[service]
    if service in spec.ONE_SHOT_SERVICES:
        assert c["State"] == "exited" and c["ExitCode"] == 0, f"{service}: {c['Status']}"
    else:
        assert c["Health"] == "healthy", f"{service}: {c['Status']}"


# --- Topología de RabbitMQ (criterio 5): el broker tiene exactamente la de topology.py.


def _is_builtin_exchange(name: str) -> bool:
    return name == "" or name.startswith("amq.")


@pytest.fixture(scope="module")
def broker(containers):
    if containers.get("rabbitmq", {}).get("State") != "running":
        pytest.skip("rabbitmq no está corriendo")
    return {
        "exchanges": compose.rabbitmqctl("list_exchanges", "name", "type", "durable"),
        "queues": compose.rabbitmqctl("list_queues", "name", "durable", "arguments"),
        "bindings": compose.rabbitmqctl("list_bindings", "source_name", "destination_name", "routing_key"),
    }


def test_exchanges_del_broker(broker):
    actual = {
        (e["name"], e["type"], e["durable"]) for e in broker["exchanges"] if not _is_builtin_exchange(e["name"])
    }
    expected = {(e.name, e.type, e.durable) for e in topology.EXCHANGES}
    assert actual == expected


def test_colas_del_broker(broker):
    actual = {(q["name"], q["durable"]) for q in broker["queues"]}
    expected = {(q.name, q.durable) for q in topology.QUEUES}
    assert actual == expected, "toda cola tiene que estar en topology.py"


@pytest.mark.parametrize("queue", topology.QUEUES, ids=lambda q: q.name)
def test_argumentos_de_cada_cola(queue, broker):
    rows = {q["name"]: q for q in broker["queues"]}
    # rabbitmqctl devuelve [nombre, tipo, valor]. El broker agrega los suyos
    # (x-queue-type), así que se exige que estén los esperados, no que sean los únicos.
    actual = {name: value for name, _type, value in rows[queue.name]["arguments"]}
    assert queue.arguments.items() <= actual.items()


def test_bindings_del_broker(broker):
    # El exchange por defecto ("") enlaza solo cada cola por su nombre: se excluye.
    actual = {
        (b["source_name"], b["destination_name"], b["routing_key"])
        for b in broker["bindings"]
        if b["source_name"] != ""
    }
    expected = {(b.exchange, b.queue, b.routing_key) for b in topology.BINDINGS}
    assert actual == expected


# --- /health de los servicios HTTP (D12), pedido desde adentro de cada contenedor.

GET_HEALTH = """
import json, urllib.error, urllib.request
try:
    response = urllib.request.urlopen("http://localhost:8000/health", timeout=5)
    code, body = response.status, response.read()
except urllib.error.HTTPError as error:
    code, body = error.code, error.read()
print(json.dumps({"code": code, "body": json.loads(body)}))
"""


@pytest.mark.parametrize("service", sorted(spec.HTTP_HEALTH_INFO))
def test_health_http(service, containers):
    if containers.get(service, {}).get("State") != "running":
        pytest.fail(f"{service} no está corriendo")
    out = compose.exec_python(service, GET_HEALTH)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    body = result["body"]
    assert result["code"] == 200, body
    assert body["service"] == service
    assert set(body["dependencies"]) == {"mongodb", "rabbitmq", "topology"}
    # Las informativas aparecen en info, y con todo levantado están en ok.
    assert body["info"] == dict.fromkeys(spec.HTTP_HEALTH_INFO[service], "ok")
