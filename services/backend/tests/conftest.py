"""Mongo real y descartable para los tests marcados `mongo`.

Mismo esquema que services/cleaning-agent/tests/conftest.py: un contenedor mongo:8.0 por
corrida, aparte del compose, que SIEMPRE se elimina (--rm, borrado al final aunque los
tests fallen, y limpieza de restos de una corrida cortada). Sin Docker, se saltean.
"""

import subprocess
import time
import uuid

import pytest

LABEL = "dcicflix.test=backend-mongo"
IMAGE = "mongo:8.0"


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout.strip()


def _remove_leftovers() -> None:
    leftovers = _docker("ps", "-aq", "--filter", f"label={LABEL}").split()
    if leftovers:
        _docker("rm", "-f", *leftovers)


@pytest.fixture(scope="session")
def mongo_address():
    """host:puerto del Mongo descartable."""
    pymongo = pytest.importorskip("pymongo")
    try:
        _docker("info", "--format", "{{.ServerVersion}}")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Docker no está corriendo: se saltean los tests contra Mongo")

    _remove_leftovers()
    container_id = _docker("run", "-d", "--rm", "--label", LABEL, "-p", "127.0.0.1::27017", IMAGE)
    try:
        address = "127.0.0.1:" + _docker("port", container_id, "27017").splitlines()[0].rsplit(":", 1)[1]
        with pymongo.MongoClient(f"mongodb://{address}", serverSelectionTimeoutMS=1000) as client:
            deadline = time.monotonic() + 60
            while True:
                try:
                    client.admin.command("ping")
                    break
                except pymongo.errors.ConnectionFailure:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.5)
        yield address
    finally:
        _docker("rm", "-f", container_id)


@pytest.fixture
def mongo_uri(mongo_address):
    """URI con una base nueva por test (la que devuelve get_default_database), borrada al terminar.

    Se entrega la URI y no un cliente: el backend usa AsyncMongoClient, que queda atado al
    event loop donde se crea, y cada test corre su propio asyncio.run.
    """
    import pymongo

    name = f"test_{uuid.uuid4().hex[:12]}"
    yield f"mongodb://{mongo_address}/{name}"
    with pymongo.MongoClient(f"mongodb://{mongo_address}") as client:
        client.drop_database(name)
