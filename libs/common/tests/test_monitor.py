"""Monitor de salud de los servicios HTTP, sin contenedores."""

import asyncio

from dcicflix_common.aio.monitor import HealthMonitor
from dcicflix_common.errors import TopologyError


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def ok():
    pass


async def caido():
    raise ConnectionError("no responde")


async def colgado():
    await asyncio.sleep(3600)


async def sin_topologia():
    raise TopologyError("falta la cola")


def test_antes_del_primer_chequeo_responde_503_arrancando():
    code, body = HealthMonitor("svc", critical={"mongodb": ok}).response()
    assert code == 503
    assert body["dependencies"] == {"mongodb": "error"}
    assert "arrancando" in body["detail"]


def test_todo_ok_responde_200():
    monitor = HealthMonitor("svc", critical={"mongodb": ok, "rabbitmq": ok})
    asyncio.run(monitor.check_once())
    code, body = monitor.response()
    assert code == 200
    assert body["status"] == "ok"


def test_critica_caida_responde_503():
    monitor = HealthMonitor("svc", critical={"mongodb": caido, "rabbitmq": ok})
    asyncio.run(monitor.check_once())
    code, body = monitor.response()
    assert code == 503
    assert body["dependencies"] == {"mongodb": "error", "rabbitmq": "ok"}


def test_informativa_caida_no_cambia_el_status():
    monitor = HealthMonitor("backend", critical={"mongodb": ok}, info={"recommender": caido})
    asyncio.run(monitor.check_once())
    code, body = monitor.response()
    assert code == 200
    assert body["info"] == {"recommender": "error"}


def test_check_colgado_vence_por_timeout():
    monitor = HealthMonitor("svc", critical={"mongodb": colgado}, check_timeout=0.05)
    asyncio.run(monitor.check_once())
    assert monitor.response()[1]["dependencies"] == {"mongodb": "error"}


def test_foto_vencida_responde_503():
    clock = FakeClock()
    monitor = HealthMonitor("svc", critical={"mongodb": ok}, clock=clock)
    asyncio.run(monitor.check_once())
    clock.now += 31
    code, body = monitor.response()
    assert code == 503
    assert "vencido" in body["detail"]


def test_error_irrecuperable_llama_a_on_fatal_y_termina():
    fatal = []
    monitor = HealthMonitor(
        "svc", critical={"topology": sin_topologia}, fatal=(TopologyError,), on_fatal=fatal.append, interval=0
    )
    asyncio.run(asyncio.wait_for(monitor.run(), 1))  # termina solo; si no, vence el timeout
    assert len(fatal) == 1 and isinstance(fatal[0], TopologyError)
