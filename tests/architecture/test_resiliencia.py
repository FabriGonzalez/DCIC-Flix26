"""Persistencia y reconexión (criterio 6): bajan y vuelven a levantar partes del sistema.

Marca slow: el `pytest` habitual no los corre (pytest.ini). Se corren con el sistema
levantado: docker compose up -d --wait && pytest -m slow
Cada test deja el sistema como lo encontró: levantado y sano. Nunca usan `down -v`.
"""

import json
import time
import uuid

import pytest

import compose
import spec
import votes
from dcicflix_common import topology

pytestmark = pytest.mark.slow

DEPENDENCIES = ("mongodb", "rabbitmq")

# Los que usan Mongo y Rabbit, según la matriz: los que tienen que notar la caída.
DATA_SERVICES = sorted(s for s, row in spec.REACHABILITY.items() if set(DEPENDENCIES) <= row["resolves"])

# Límites con margen sobre lo medido en F6: unhealthy a los ~28 s de la caída
# (3 healthchecks de 10 s), healthy a los ~48 s de que vuelven Mongo y Rabbit.
DETECT_TIMEOUT = 90
RECOVER_TIMEOUT = 180
UP_TIMEOUT = 300
POLL = 2

# Colección solo del test, para el centinela de Mongo. Se borra al terminar.
SENTINEL_COLLECTION = "_test_persistencia"

# El centinela de Rabbit va a la cola de errores, que no consume nadie.
SENTINEL_QUEUE = topology.INTERACTIONS_ERRORS_QUEUE

# Rabbit no tiene un cliente de línea de comandos que publique: se usa pika desde un
# worker, con sus propias variables de entorno. Confirmaciones del broker (confirm_delivery)
# y mensaje persistente: cuando basic_publish vuelve, el broker ya lo guardó.
_RABBIT = """
import json, os, sys, pika
params = pika.ConnectionParameters(
    os.environ["RABBITMQ_HOST"],
    credentials=pika.PlainCredentials(os.environ["RABBITMQ_USER"], os.environ["RABBITMQ_PASSWORD"]),
)
action, queue = sys.argv[1], sys.argv[2]
with pika.BlockingConnection(params) as connection:
    channel = connection.channel()
    if action == "publish":
        channel.confirm_delivery()
        channel.basic_publish("", queue, sys.argv[3].encode(),
                              pika.BasicProperties(delivery_mode=2), mandatory=True)
    else:  # take: saca un mensaje de la cola (auto_ack lo borra)
        method, _properties, body = channel.basic_get(queue, auto_ack=True)
        print(json.dumps(None if method is None else body.decode()))
"""
_RABBIT_CLIENT = "ingest-consumer"


# --- Esperas


def _not_ready() -> str | None:
    """Qué servicios no están como pide el criterio 1, o None si están todos."""
    found = compose.containers()
    pending = []
    for service in compose.services():
        c = found.get(service)
        if c is None:
            pending.append(f"{service}: sin contenedor")
        elif service in spec.ONE_SHOT_SERVICES:
            if not (c["State"] == "exited" and c["ExitCode"] == 0):
                pending.append(f"{service}: {c['Status']}")
        elif c["Health"] != "healthy":
            pending.append(f"{service}: {c['Status']}")
    return ", ".join(pending) or None


def _still_healthy(services: list[str]) -> str | None:
    """Cuáles de `services` siguen healthy, o None si ya ninguno lo está."""
    found = compose.containers()
    healthy = [s for s in services if found.get(s, {}).get("Health") == "healthy"]
    return ", ".join(healthy) or None


def _wait_until(pending, timeout: float, goal: str) -> float:
    """Espera hasta que `pending()` devuelva None. Devuelve los segundos que tardó."""
    start = time.monotonic()
    while (left := pending()) is not None:
        if time.monotonic() - start > timeout:
            pytest.fail(f"{timeout} s esperando {goal}; faltan: {left}")
        time.sleep(POLL)
    return time.monotonic() - start


@pytest.fixture
def sistema_sano():
    if not compose.containers():
        pytest.skip("no hay nada levantado: correr `docker compose up -d --wait`")
    # Espera en vez de fallar: Docker marca unhealthy al tercer healthcheck, y con una caída
    # corta eso puede llegar cuando el servicio ya se recuperó y el test anterior terminó.
    _wait_until(_not_ready, RECOVER_TIMEOUT, "que el sistema esté sano antes de empezar")


def _ok(*args: str) -> None:
    """`docker compose <args>`, y si falla, el test falla con su stderr."""
    result = compose.run(*args, check=False)
    if result.returncode != 0:
        pytest.fail(f"docker compose {' '.join(args)} terminó con {result.returncode}:\n{result.stderr}")


# --- Centinelas


def _mongo(script: str):
    result = compose.mongosh(script)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _mongo_counts() -> dict[str, int]:
    return _mongo("print(JSON.stringify({movies: db.movies.countDocuments(), reviews: db.reviews.countDocuments()}))")


def _rabbit(*args: str):
    result = compose.exec_python(_RABBIT_CLIENT, _RABBIT, *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def _messages_in(queue: str) -> int:
    rows = {q["name"]: q for q in compose.rabbitmqctl("list_queues", "name", "messages")}
    return rows[queue]["messages"]


# --- Tests


def test_los_datos_sobreviven_a_down_y_up(sistema_sano):
    """Criterio 6: tras down + up todo vuelve a healthy, y los volúmenes conservan los datos.

    Contar no alcanza: con el volumen perdido, mongo-init.sh vuelve a cargar el dataset y
    las cantidades dan igual. El centinela (un uuid nuevo en cada corrida) solo sobrevive
    si el volumen persistió. Las cantidades detectan una carga duplicada.
    """
    if _messages_in(SENTINEL_QUEUE) != 0:
        pytest.skip(f"{SENTINEL_QUEUE} tiene mensajes; vaciarla con rabbitmqctl purge_queue {SENTINEL_QUEUE}")
    token = uuid.uuid4().hex
    try:
        before = _mongo_counts()
        _mongo(f'db.getCollection("{SENTINEL_COLLECTION}").insertOne({{_id: "{token}"}}); print("null")')
        _rabbit("publish", SENTINEL_QUEUE, token)
        assert _messages_in(SENTINEL_QUEUE) == 1

        start = time.monotonic()
        _ok("down")
        # Sin --profile, down no toca frontend-dev (perfil dev): si estaba levantado, sigue.
        left = set(compose.containers()) & set(compose.services())
        assert not left, f"down dejó contenedores: {left}"
        _ok("up", "-d", "--wait", "--wait-timeout", str(UP_TIMEOUT))
        print(f"down + up: {time.monotonic() - start:.0f} s")

        assert _not_ready() is None
        assert _mongo_counts() == before, "cambió la cantidad de documentos: ¿se volvió a cargar el dataset?"
        found = _mongo(f'print(JSON.stringify(db.getCollection("{SENTINEL_COLLECTION}").findOne({{_id: "{token}"}})))')
        assert found == {"_id": token}, "el centinela de Mongo no sobrevivió: se perdió el volumen mongo-data"
        assert _messages_in(SENTINEL_QUEUE) == 1, "el centinela de Rabbit no sobrevivió: se perdió rabbitmq-data"
        assert _rabbit("take", SENTINEL_QUEUE) == token
    finally:
        # Sin check: si el sistema no volvió, la falla ya está informada arriba.
        compose.mongosh(f'db.getCollection("{SENTINEL_COLLECTION}").drop()')
        compose.run("exec", "-T", "rabbitmq", "rabbitmqctl", "-q", "purge_queue", SENTINEL_QUEUE, check=False)


def test_los_servicios_se_reconectan_solos(sistema_sano):
    """Mongo y Rabbit se caen con los servicios corriendo: todos reconectan sin reinicios.

    Primero se espera a que lo noten (unhealthy): una caída que nadie nota no prueba nada.
    Con `start`, topology-init no vuelve a correr: la topología sale del volumen de Rabbit.
    """
    before = compose.inspect()

    _ok("stop", *DEPENDENCIES)
    try:
        detected = _wait_until(lambda: _still_healthy(DATA_SERVICES), DETECT_TIMEOUT, "que noten la caída")
        print(f"unhealthy a los {detected:.0f} s de la caída")

        # D12: el frontend no depende de los datos, y el backend sigue respondiendo:
        # informa la caída con un 503, no deja de contestar.
        assert compose.containers()["frontend"]["Health"] == "healthy"
        code, content_type, body = compose.get_from_frontend("/api/health")
        assert content_type.startswith("application/json"), f"nginx no llegó al backend: HTTP {code}"
        assert code == 503, body
        dependencies = json.loads(body)["dependencies"]
        assert {d: dependencies[d] for d in DEPENDENCIES} == dict.fromkeys(DEPENDENCIES, "error")
    finally:
        _ok("start", *DEPENDENCIES)

    recovered = _wait_until(_not_ready, RECOVER_TIMEOUT, "que todo vuelva a healthy")
    print(f"healthy a los {recovered:.0f} s de que volvieron {', '.join(DEPENDENCIES)}")

    after = compose.inspect()
    restarts = {
        s: (before[s]["RestartCount"], after[s]["RestartCount"])
        for s in DATA_SERVICES
        if before[s]["RestartCount"] != after[s]["RestartCount"]
    }
    assert not restarts, f"reconectar no tendría que reiniciar el contenedor (D14): {restarts}"
    assert after["topology-init"]["State"]["StartedAt"] == before["topology-init"]["State"]["StartedAt"]
    code, _content_type, body = compose.get_from_frontend("/api/health")
    assert code == 200, body


# --- Votos (docs/ingest-consumer.md): ninguno se pierde ni se guarda dos veces
#
# Los que usan `voter` publican en la cola; los de `api_voter`, votan por la API.


@pytest.fixture
def voter(sistema_sano):
    voter = votes.Voter()
    yield voter
    voter.clean()


def _unsettled(voter, rating: int):
    """Qué falta para que el voto esté guardado una vez y confirmado, o None."""
    saved, state = voter.saved(), votes.queue()
    if saved == [rating] and votes.is_drained():
        return None
    return f"votos guardados {saved}, cola {state}"


def _restarts() -> int:
    return compose.inspect()["ingest-consumer"]["RestartCount"]


def test_un_voto_espera_a_que_vuelva_mongo(voter):
    """Mongo caído no es culpa del mensaje: espera sin ir a errores y sin reiniciar el consumer."""
    before, errors = _restarts(), _messages_in(SENTINEL_QUEUE)
    _ok("stop", "mongodb")
    try:
        voter.publish(rating=3)
        # Más que el plazo de 3 s con que pymongo busca al servidor: hubo intentos fallidos.
        time.sleep(15)
        assert votes.queue()["messages_unacknowledged"] == 1, "el consumer no tiene el mensaje esperando"
    finally:
        _ok("start", "mongodb")
        _wait_until(_not_ready, RECOVER_TIMEOUT, "que todo vuelva a healthy")
    _wait_until(lambda: _unsettled(voter, 3), DETECT_TIMEOUT, "que se guarde el voto")
    assert voter.added_to_count() == 1
    assert _messages_in(SENTINEL_QUEUE) == errors, "el voto terminó en la cola de errores"
    assert _restarts() == before


# El consumer real, con una sola diferencia: muere al ir a confirmar, con el voto ya guardado.
_DIES_BEFORE_ACK = """
import os, sys
sys.path.insert(0, "/app")
from pika.adapters.blocking_connection import BlockingChannel
BlockingChannel.basic_ack = lambda self, tag: os._exit(137)
from dcicflix_common.sync import worker
import main
worker.main("test", main.setup)
"""


def test_morir_entre_guardar_y_confirmar_no_duplica_el_voto(voter):
    _ok("stop", "ingest-consumer")
    try:
        voter.publish(rating=5)
        dying = compose.run(
            "run", "--rm", "--no-deps", "-T", "ingest-consumer", "python", "-c", _DIES_BEFORE_ACK, check=False
        )
        assert dying.returncode == 137, dying.stderr
        # Si no, el test no probaría nada: guardado, y el mensaje todavía en la cola.
        assert voter.saved() == [5]
        assert votes.queue()["messages_ready"] == 1
    finally:
        _ok("start", "ingest-consumer")
    _wait_until(lambda: _unsettled(voter, 5), DETECT_TIMEOUT, "que se procese la reentrega")
    assert voter.added_to_count() == 1
    _wait_until(_not_ready, RECOVER_TIMEOUT, "que todo vuelva a healthy")


@pytest.fixture
def api_voter(voter):
    voter.register()
    return voter


def _system_state() -> str | None:
    code, _content_type, body = compose.get_from_frontend("/api/status")
    return json.loads(body)["state"] if code == 200 else None


def _not_in_state(state: str):
    return lambda: None if (now := _system_state()) == state else f"el estado es {now}"


def _vote_until_accepted(voter, rating: int) -> None:
    """Tras una caída, el estado puede ir y volver de ready unos segundos: el recommender
    informa 503 hasta su próximo chequeo, y el backend lo nota en el suyo (10 s cada uno)."""

    def pending():
        code = voter.post(rating)
        return None if code == 202 else f"HTTP {code}"

    _wait_until(pending, RECOVER_TIMEOUT, "que se acepte el voto")


def test_un_voto_aceptado_espera_al_consumer(api_voter):
    """Aceptar no depende del consumer: si está detenido, el voto queda en la cola."""
    _ok("stop", "ingest-consumer")
    try:
        _vote_until_accepted(api_voter, 4)
        assert votes.queue()["messages_ready"] == 1
        assert api_voter.saved() == []
    finally:
        _ok("start", "ingest-consumer")
    _wait_until(lambda: _unsettled(api_voter, 4), DETECT_TIMEOUT, "que se guarde el voto")
    _wait_until(_not_ready, RECOVER_TIMEOUT, "que todo vuelva a healthy")


# Sin Rabbit, 503 (no se pudo publicar) hasta que el recommender también lo nota: desde
# ahí el estado es indexing, y 409. Sin Mongo no se puede leer el estado: siempre 503.
@pytest.mark.parametrize("dependency, rejections", [("mongodb", {503}), ("rabbitmq", {503, 409})])
def test_sin_mongo_o_sin_rabbit_no_se_acepta_el_voto(api_voter, dependency, rejections):
    """Responder 202 sería prometer un voto que se puede perder."""
    _ok("stop", dependency)
    try:
        assert api_voter.post(2) in rejections
    finally:
        _ok("start", dependency)
        _wait_until(_not_ready, RECOVER_TIMEOUT, "que todo vuelva a healthy")
    assert api_voter.saved() == [], "el voto rechazado se guardó"
    _vote_until_accepted(api_voter, 5)
    _wait_until(lambda: _unsettled(api_voter, 5), DETECT_TIMEOUT, "que se guarde el voto")


def test_sin_recommender_el_sistema_no_esta_listo_para_votar(api_voter):
    _ok("stop", "recommender")
    try:
        _wait_until(_not_in_state("indexing"), DETECT_TIMEOUT, "que el backend note la caída")
        assert api_voter.post(3) == 409
    finally:
        _ok("start", "recommender")
        _wait_until(_not_ready, RECOVER_TIMEOUT, "que todo vuelva a healthy")
    _vote_until_accepted(api_voter, 3)
    _wait_until(lambda: _unsettled(api_voter, 3), DETECT_TIMEOUT, "que se guarde el voto")
