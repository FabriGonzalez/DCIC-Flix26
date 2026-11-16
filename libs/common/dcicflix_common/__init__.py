"""Helper compartido de los servicios Python de DCIC-Flix.

El núcleo (config, logging, topology) no importa dependencias externas.
La I/O vive en las variantes `sync/` (pika, MongoClient) y `aio/` (aio-pika,
AsyncMongoClient), que se instalan con los extras [sync] y [async].
"""
