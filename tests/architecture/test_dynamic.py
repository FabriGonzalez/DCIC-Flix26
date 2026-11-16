"""Verificaciones sobre el sistema levantado: docker compose up -d --wait"""

import pytest

import compose
import spec

pytestmark = pytest.mark.dynamic

SERVICES = sorted(compose.services())


@pytest.fixture(scope="module")
def containers():
    found = compose.containers()
    if not found:
        pytest.skip("no hay nada levantado: correr `docker compose up -d --wait`")
    return found


@pytest.mark.parametrize("service", SERVICES)
def test_servicio_sano(service, containers):
    """Criterio 1: todo healthy, y los servicios de una sola vez en Exited (0)."""
    assert service in containers, f"{service} no tiene contenedor"
    c = containers[service]
    if service in spec.ONE_SHOT_SERVICES:
        assert c["State"] == "exited" and c["ExitCode"] == 0, f"{service}: {c['Status']}"
    else:
        assert c["Health"] == "healthy", f"{service}: {c['Status']}"
