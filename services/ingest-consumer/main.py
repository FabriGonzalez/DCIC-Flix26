"""ingest-consumer: stub conectado (D1).

Por ahora solo se conecta a Mongo y a Rabbit, verifica la topología y escribe el
latido. Más adelante consume la cola `interactions` y persiste los votos.
"""

from dcicflix_common import logging as logs
from dcicflix_common.sync import worker

SERVICE = "ingest-consumer"

if __name__ == "__main__":
    logs.setup(SERVICE)
    worker.main(SERVICE)
