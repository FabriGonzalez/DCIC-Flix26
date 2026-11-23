"""ingest-consumer: consume la cola `interactions` y guarda los votos en MongoDB.

Corre sobre el bucle común de los workers, que atiende la conexión, el latido y la
reconexión. Qué se hace con cada mensaje está en ingest/consumer.py.
"""

from pymongo import MongoClient

from dcicflix_common import logging as logs
from dcicflix_common.config import MongoSettings
from dcicflix_common.sync import worker
from ingest import store
from ingest.consumer import Consumer

SERVICE = "ingest-consumer"


def setup(mongo_client: MongoClient) -> worker.Hooks:
    db = mongo_client[MongoSettings.from_env().db]
    store.ensure_indexes(db)
    consumer = Consumer(db)
    return worker.Hooks(on_connect=consumer.on_connect, tick=consumer.tick)


if __name__ == "__main__":
    logs.setup(SERVICE)
    worker.main(SERVICE, setup)
