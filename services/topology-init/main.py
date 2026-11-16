"""Declara la topología de RabbitMQ y termina (D10).

Exited (0) es el resultado esperado. Si termina con código 1, el log dice por qué:
broker inalcanzable tras los reintentos, credenciales rechazadas, o una cola ya
existente con otros argumentos (PRECONDITION_FAILED).
"""

import logging
import sys

from pika.exceptions import AMQPError

from dcicflix_common import logging as logs
from dcicflix_common import topology
from dcicflix_common.config import ConfigError, RabbitSettings
from dcicflix_common.sync import rabbit

SERVICE = "topology-init"
# depends_on ya espera a que rabbitmq esté healthy; esto es solo un margen.
CONNECT_RETRY_SECONDS = 60

log = logging.getLogger(SERVICE)


def main() -> None:
    settings = RabbitSettings.from_env()
    connection = rabbit.connect(settings, retry_for=CONNECT_RETRY_SECONDS)
    try:
        rabbit.declare_topology(connection.channel())
        rabbit.verify_topology(connection)
    finally:
        connection.close()
    log.info(
        "topología declarada: %d exchanges, %d colas, %d bindings",
        len(topology.EXCHANGES),
        len(topology.QUEUES),
        len(topology.BINDINGS),
    )


if __name__ == "__main__":
    logs.setup(SERVICE)
    try:
        main()
    except (ConfigError, AMQPError, OSError, rabbit.TopologyError) as exc:
        log.error("no se pudo declarar la topología: %s: %s", type(exc).__name__, exc)
        sys.exit(1)
