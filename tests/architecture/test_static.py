"""Verificaciones sobre `docker compose config`. No necesitan nada levantado."""

import pytest

import compose
import spec

pytestmark = pytest.mark.static

SERVICES = sorted(compose.services())


def test_no_hay_redes_fuera_del_diseno():
    # `compose config` omite las redes que ningún servicio usa, así que se compara
    # por inclusión. Que cada red conecte lo que debe lo prueba la matriz de alcance.
    networks = set(compose.config()["networks"])
    assert "default" not in networks, "algún servicio quedó en la red default"
    assert networks <= spec.NETWORKS, f"redes fuera del diseño: {networks - spec.NETWORKS}"


@pytest.mark.parametrize("network", sorted(spec.INTERNAL_NETWORKS))
def test_redes_internas_sin_salida(network):
    assert compose.config()["networks"][network].get("internal") is True


@pytest.mark.parametrize("service", SERVICES)
def test_servicio_declara_sus_redes(service):
    # Sin `networks:` explícito, Compose lo conecta a la red `default`.
    networks = set(compose.services()[service].get("networks", {}))
    assert networks, f"{service} no declara networks:"
    assert networks <= spec.NETWORKS, f"{service} usa redes fuera del diseño: {networks - spec.NETWORKS}"


@pytest.mark.parametrize("service", SERVICES)
def test_solo_el_frontend_publica_puertos(service):
    published = [p for p in compose.services()[service].get("ports", []) if p.get("published")]
    if service not in spec.PUBLISHED_PORTS_ALLOWED:
        assert not published, f"{service} publica puertos en el host: {published}"


@pytest.mark.parametrize("service", SERVICES)
def test_imagenes_con_tag_fijo(service):
    svc = compose.services()[service]
    if "build" in svc:
        pytest.skip("imagen propia")
    image = svc["image"]
    # El tag va después del último "/", para no confundirlo con el puerto de un registry.
    _, _, tag = image.split("/")[-1].partition(":")
    assert tag and tag != "latest", f"{service} usa {image}: fijar un tag de versión"


@pytest.mark.parametrize("service", SERVICES)
def test_politica_de_reinicio(service):
    expected = "no" if service in spec.ONE_SHOT_SERVICES else spec.LONG_LIVED_RESTART
    assert compose.services()[service].get("restart", "no") == expected


@pytest.mark.parametrize("service", SERVICES)
def test_servicios_de_larga_vida_con_healthcheck(service):
    if service in spec.ONE_SHOT_SERVICES:
        pytest.skip("servicio de una sola vez")
    healthcheck = compose.services()[service].get("healthcheck", {})
    assert healthcheck.get("test") and not healthcheck.get("disable"), f"{service} no tiene healthcheck"
