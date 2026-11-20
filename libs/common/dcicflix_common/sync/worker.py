"""Bucle común de los workers sincrónicos: el stub "conectado" (D1).

Se conecta a Mongo y a Rabbit, verifica la topología en forma pasiva (D10), escribe el
latido (D13) y aplica la política ante fallas (D14):

    Mongo no responde              → el latido dice "error"; pymongo se reconecta solo
    Rabbit se corta                → el latido dice "error"; este bucle reconecta
    credenciales rechazadas        → el proceso termina con código 1
    topología faltante             → el proceso termina con código 1
    (restart: unless-stopped lo vuelve a levantar)

El hilo principal es el único que toca la conexión de pika (no es thread-safe) y la
atiende con process_data_events, que además mantiene el heartbeat AMQP. Con más de 30 s
sin atenderla, el broker la corta. Por eso un servicio con trabajo largo lo hace en otro
hilo y engancha un `setup` (ver `run`): el hilo principal sigue atendiendo la conexión
y, en cada vuelta, llama al `tick` del servicio, que es quien usa la conexión.
"""

import logging
import signal
import sys
import time
from collections.abc import Callable

import pika
from pika.exceptions import AMQPError, AMQPConnectionError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from dcicflix_common import health
from dcicflix_common.config import ConfigError, MongoSettings, RabbitSettings
from dcicflix_common.errors import BackgroundTaskError
from dcicflix_common.sync import mongo, rabbit
from dcicflix_common.sync.heartbeat import INTERVAL, Heartbeat, HealthState

log = logging.getLogger(__name__)

# Dependencias que reporta el hilo principal (pika). Mongo lo comprueba el latido.
_REPORTED = ("rabbitmq", "topology")
_TOPOLOGY_CHECK_INTERVAL = INTERVAL

# Se llama en el hilo principal en cada vuelta (~1 s), con la conexión abierta.
Tick = Callable[[pika.BlockingConnection], None]
# Se llama una vez, con Mongo listo; arranca el trabajo del servicio y devuelve su tick.
Setup = Callable[[MongoClient], Tick]


def run(service: str, setup: Setup | None = None) -> None:
    """Corre el worker hasta que algo irrecuperable lo termine.

    setup: trabajo propio del servicio (por ejemplo, la limpieza). Sin setup, el worker
    solo se mantiene conectado.
    """
    mongo_settings = MongoSettings.from_env()
    rabbit_settings = RabbitSettings.from_env()

    mongo_client = mongo.client(mongo_settings)
    state = HealthState()
    Heartbeat(service, state, reported=_REPORTED, checks={"mongodb": lambda: mongo.ping(mongo_client)}).start()

    # Esperar a Mongo al arrancar sirve para detectar credenciales rechazadas, que son
    # irrecuperables. Después, una caída de Mongo solo la informa el latido.
    mongo.wait_until_ready(mongo_client)
    tick = setup(mongo_client) if setup else None

    while True:
        connection = rabbit.connect(rabbit_settings, name=service)
        try:
            _serve(connection, state, tick)
        except AMQPConnectionError as exc:
            # Se cortó la conexión (broker detenido, red, heartbeat AMQP vencido): recuperable.
            log.warning("se perdió la conexión con RabbitMQ (%s: %s); reconectando", type(exc).__name__, exc)
            state.report("rabbitmq", health.ERROR)
            state.report("topology", health.ERROR)
        finally:
            _close_quietly(connection)


def _serve(connection: pika.BlockingConnection, state: HealthState, tick: Tick | None = None) -> None:
    """Atiende la conexión y verifica la topología cada 10 s, hasta que se corte."""
    next_topology_check = 0.0
    while True:
        if time.monotonic() >= next_topology_check:
            rabbit.verify_topology(connection)  # TopologyError: irrecuperable, se propaga
            state.report("topology", health.OK)
            next_topology_check = time.monotonic() + _TOPOLOGY_CHECK_INTERVAL
        state.report("rabbitmq", health.OK)
        # Atiende el socket hasta 1 s: heartbeat AMQP, y en el futuro, los mensajes.
        # Si la conexión se cortó, lanza AMQPConnectionError.
        connection.process_data_events(time_limit=1)
        if tick:
            tick(connection)


def _close_quietly(connection: pika.BlockingConnection) -> None:
    if connection.is_open:
        try:
            connection.close()
        except AMQPError:
            pass


def _exit_on_sigterm(signum, frame) -> None:
    # Python como PID 1 ignora SIGTERM si no instala un handler: `docker stop`
    # esperaría 10 s y lo mataría con SIGKILL.
    raise SystemExit(0)


def main(service: str, setup: Setup | None = None) -> None:
    """Punto de entrada de los workers: corre el bucle y traduce lo irrecuperable a código 1."""
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        run(service, setup)
    except (ConfigError, AMQPError, PyMongoError, rabbit.TopologyError, BackgroundTaskError, OSError) as exc:
        logging.getLogger(service).error("error irrecuperable, termino: %s: %s", type(exc).__name__, exc)
        sys.exit(1)
