"""Mongo real y descartable para los tests marcados `mongo`.

Se levanta un contenedor mongo:8.0 por corrida, aparte del compose (sus datos no se
tocan), y SIEMPRE se elimina: se crea con --rm, se borra al final aunque los tests
fallen, y al arrancar se borran los que hayan quedado de una corrida cortada (Ctrl+C).
Si Docker no está corriendo, esos tests se saltean con aviso.
"""

import subprocess
import time
import uuid

import pytest

LABEL = "dcicflix.test=mongo"
IMAGE = "mongo:8.0"


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout.strip()


def _removeLeftovers() -> None:
    leftovers = _docker("ps", "-aq", "--filter", f"label={LABEL}").split()
    if leftovers:
        _docker("rm", "-f", *leftovers)


@pytest.fixture(scope="session")
def mongoClient():
    pymongo = pytest.importorskip("pymongo")
    try:
        _docker("info", "--format", "{{.ServerVersion}}")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Docker no está corriendo: se saltean los tests contra Mongo")

    _removeLeftovers()
    containerId = _docker("run", "-d", "--rm", "--label", LABEL, "-p", "127.0.0.1::27017", IMAGE)
    client = None
    try:
        port = _docker("port", containerId, "27017").splitlines()[0].rsplit(":", 1)[1]
        client = pymongo.MongoClient(f"mongodb://127.0.0.1:{port}", serverSelectionTimeoutMS=1000)
        deadline = time.monotonic() + 60
        while True:
            try:
                client.admin.command("ping")
                break
            except pymongo.errors.ConnectionFailure:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        yield client
    finally:
        if client is not None:
            client.close()
        _docker("rm", "-f", containerId)


@pytest.fixture
def db(mongoClient):
    """Una base nueva por test, borrada al terminar."""
    name = f"test_{uuid.uuid4().hex[:12]}"
    yield mongoClient[name]
    mongoClient.drop_database(name)
