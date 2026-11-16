"""Alcance y aislamiento (criterios 4 y 5), desde adentro de cada contenedor.

Los datos están en spec.REACHABILITY. Se hace un solo `docker compose exec` por
servicio: el script prueba todos los nombres y destinos, y devuelve un JSON.
"""

import json
import socket

import pytest

import compose
import spec

pytestmark = pytest.mark.dynamic

# Corre dentro del contenedor. argv[1]: nombres a resolver; argv[2]: destinos "host:puerto".
PROBE = """
import json, socket, sys
names, targets = json.loads(sys.argv[1]), json.loads(sys.argv[2])
def resolves(name):
    try:
        socket.getaddrinfo(name, None)
        return True
    except OSError:
        return False
def connects(host, port):
    try:
        socket.create_connection((host, port), timeout=5).close()
        return True
    except OSError:
        return False
print(json.dumps({
    "resolves": {name: resolves(name) for name in names},
    "connects": {f"{h}:{p}": connects(h, p) for h, p in targets},
}))
"""

EXISTING = set(compose.services())


def _cases(kind: str, arrow: str) -> list:
    return [
        pytest.param(service, name, id=f"{service}{arrow}{name}")
        for service, reach in spec.REACHABILITY.items()
        for name in sorted(reach[kind])
    ]


def _skip_if_missing(name: str) -> None:
    if name not in EXISTING:
        pytest.skip(f"{name} todavía no existe en el compose")


@pytest.fixture(scope="module")
def probes():
    """Resultado del PROBE en cada servicio de la matriz, calculado una sola vez."""
    containers = compose.containers()
    results = {}
    for service, reach in spec.REACHABILITY.items():
        if containers.get(service, {}).get("State") != "running":
            continue
        names = sorted(reach["resolves"] | reach["not_resolves"])
        out = compose.exec_python(service, PROBE, json.dumps(names), json.dumps(spec.INTERNET_PROBES))
        assert out.returncode == 0, f"{service}: el probe falló: {out.stderr}"
        results[service] = json.loads(out.stdout)
    return results


def _probe(probes, service):
    if service not in probes:
        pytest.fail(f"{service} no está corriendo: correr `docker compose up -d --wait`")
    return probes[service]


@pytest.fixture(scope="module")
def host_online():
    """Sin internet en el host, los tests de salida no prueban nada: se saltean."""
    for host, port in spec.INTERNET_PROBES:
        try:
            socket.create_connection((host, port), timeout=5).close()
        except OSError:
            pytest.skip(f"el host no tiene conexión a internet ({host}:{port}); no se prueba la salida")


@pytest.mark.parametrize(("service", "name"), _cases("resolves", "->"))
def test_resuelve_sus_dependencias(service, name, probes):
    _skip_if_missing(name)
    assert _probe(probes, service)["resolves"][name], f"{service} no resuelve {name}"


@pytest.mark.parametrize(("service", "name"), _cases("not_resolves", "-x->"))
def test_no_resuelve_lo_aislado(service, name, probes):
    _skip_if_missing(name)
    assert not _probe(probes, service)["resolves"][name], f"{service} resuelve {name}: tendría que estar aislado"


@pytest.mark.parametrize("service", sorted(spec.REACHABILITY))
def test_salida_a_internet(service, probes, host_online):
    expected = spec.REACHABILITY[service]["internet"]
    actual = _probe(probes, service)["connects"]
    assert actual == {f"{h}:{p}": expected for h, p in spec.INTERNET_PROBES}, (
        f"{service}: se esperaba {'salida' if expected else 'sin salida'} a internet"
    )
