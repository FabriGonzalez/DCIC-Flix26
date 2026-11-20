"""cleaning-agent: limpia el dataset una vez y publica `data.cleaned`.

    hilo de limpieza:   runCleaning (marca running → done)
    hilo principal:     atiende Rabbit (bucle común) y, en cada vuelta, el tick:
                        - si la limpieza falló → termina con código 1 (Docker lo reinicia
                          y la limpieza se repite desde la copia cruda)
                        - si la marca dice done y el evento no salió → lo publica y lo anota

La limpieza va en otro hilo porque puede tardar minutos, y el hilo principal tiene que
seguir atendiendo la conexión de Rabbit y el latido (D13). Publica el hilo principal
porque la conexión de pika no se puede usar desde dos hilos.
"""

import json
import logging
import threading

import pika
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure

from app import runner, store
from dcicflix_common import config, topology
from dcicflix_common import logging as logs
from dcicflix_common.config import MongoSettings
from dcicflix_common.errors import BackgroundTaskError
from dcicflix_common.sync import worker

SERVICE = "cleaning-agent"
log = logging.getLogger(SERVICE)


class CleaningJob:
    def __init__(self, db: Database):
        self.db = db
        self.error: BaseException | None = None
        self.published = False
        # daemon: un SIGTERM no espera a que termine la limpieza; al volver, se repite.
        self.thread = threading.Thread(target=self._run, name="cleaning", daemon=True)

    def _run(self) -> None:
        try:
            runner.runCleaning(self.db)
        except BaseException as exc:  # cualquier falla la informa el hilo principal
            self.error = exc

    def tick(self, connection: pika.BlockingConnection) -> None:
        if self.published or self.thread.is_alive():
            return
        if self.error is not None:
            raise BackgroundTaskError(f"falló la limpieza: {type(self.error).__name__}: {self.error}") from self.error
        try:
            if runner.eventPending(self.db):
                publishDataCleaned(connection, store.readState(self.db))
                runner.markEventPublished(self.db)
                log.info("publicado %s", topology.DATA_CLEANED_EXCHANGE)
        except ConnectionFailure as exc:
            # Mongo caído: se reintenta en la próxima vuelta (D14). Si el evento salió y no
            # se llegó a anotar, se publica de nuevo: el recomendador tolera duplicados.
            log.warning("no se pudo leer o anotar la marca (%s); reintento", type(exc).__name__)
            return
        self.published = True


def publishDataCleaned(connection: pika.BlockingConnection, state: dict) -> None:
    channel = connection.channel()
    # Con confirmaciones, basic_publish vuelve cuando el broker ya guardó el mensaje.
    channel.confirm_delivery()
    channel.basic_publish(
        exchange=topology.DATA_CLEANED_EXCHANGE,
        routing_key="",
        body=json.dumps({"finishedAt": state["finishedAt"].isoformat()}).encode(),
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
    )
    channel.close()


def setup(mongoClient: MongoClient) -> worker.Tick:
    job = CleaningJob(mongoClient[MongoSettings.from_env().db])
    job.thread.start()
    return job.tick


if __name__ == "__main__":
    logs.setup(SERVICE)
    # Sin API key la app funciona: la limpieza con LLM queda deshabilitada (D15).
    if config.llm_api_key() is None:
        log.warning("sin LLM_API_KEY: la limpieza con LLM queda deshabilitada")
    worker.main(SERVICE, setup)
