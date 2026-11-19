"""Latido y healthcheck de los workers, sin contenedores."""

import json
import time
from datetime import datetime, timedelta, timezone

from dcicflix_common import health
from dcicflix_common.sync import healthcheck
from dcicflix_common.sync.heartbeat import Heartbeat, HealthState


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_status_ok_solo_si_todas_las_criticas_estan_ok():
    assert health.report("svc", {"mongodb": "ok", "rabbitmq": "ok"})["status"] == "ok"
    assert health.report("svc", {"mongodb": "ok", "rabbitmq": "error"})["status"] == "error"


def test_las_informativas_no_cambian_el_status():
    assert health.report("svc", {"mongodb": "ok"}, info={"recommender": "error"})["status"] == "ok"


def test_reporte_vencido_o_inexistente_es_error():
    clock = FakeClock()
    state = HealthState(clock)
    state.report("rabbitmq", "ok")
    clock.now += 30
    assert state.snapshot(("rabbitmq", "topology")) == {"rabbitmq": "ok", "topology": "error"}
    clock.now += 1
    assert state.snapshot(("rabbitmq",)) == {"rabbitmq": "error"}


def test_check_que_falla_marca_error(tmp_path):
    def mongo_caido():
        raise ConnectionError("no responde")

    state = HealthState()
    state.report("rabbitmq", "ok")
    beat = Heartbeat("svc", state, reported=("rabbitmq",), checks={"mongodb": mongo_caido}, path=tmp_path / "h.json")
    data = beat.beat()
    assert data["status"] == "error"
    assert data["dependencies"] == {"rabbitmq": "ok", "mongodb": "error"}
    assert json.loads((tmp_path / "h.json").read_text()) == data


def test_start_borra_la_nota_de_un_proceso_anterior(tmp_path):
    path = tmp_path / "h.json"
    path.write_text('{"status": "ok", "service": "proceso-anterior"}')
    Heartbeat("svc", HealthState(), path=path, interval=3600).start()
    # El hilo escribe enseguida su primer latido: hay que ver el nuevo, no el viejo.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if path.exists() and json.loads(path.read_text()).get("service") == "svc":
            break
        time.sleep(0.01)
    assert json.loads(path.read_text())["service"] == "svc"


def _write(path, status="ok", age=0.0):
    written = datetime.now(timezone.utc) - timedelta(seconds=age)
    path.write_text(json.dumps({"status": status, "dependencies": {}, "time": written.isoformat()}))


def test_healthcheck_sano(tmp_path):
    _write(tmp_path / "h.json")
    assert healthcheck.problem(tmp_path / "h.json") is None


def test_healthcheck_sin_nota(tmp_path):
    assert "no hay latido" in healthcheck.problem(tmp_path / "h.json")


def test_healthcheck_nota_vencida(tmp_path):
    _write(tmp_path / "h.json", age=31)
    assert "vencido" in healthcheck.problem(tmp_path / "h.json")


def test_healthcheck_estado_error(tmp_path):
    _write(tmp_path / "h.json", status="error")
    assert "error" in healthcheck.problem(tmp_path / "h.json")


def test_healthcheck_nota_ilegible(tmp_path):
    (tmp_path / "h.json").write_text("{a medio escribir")
    assert "ilegible" in healthcheck.problem(tmp_path / "h.json")


def test_explain_distingue_error_reportado_de_reporte_vencido():
    clock = FakeClock()
    state = HealthState(clock)
    assert state.explain("rabbitmq") == "sin reporte todavía"
    state.report("rabbitmq", "error")
    assert state.explain("rabbitmq") == "reportado 'error'"
    clock.now += 45
    assert state.explain("rabbitmq") == "sin reporte hace 45 s"
