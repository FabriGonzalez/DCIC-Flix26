"""Latido de los workers sin HTTP (D13): un hilo escribe /tmp/health.json cada 10 s.

Docker no puede preguntarle a un worker si está sano, así que el worker deja una nota
con su estado y la hora, y el healthcheck (`sync/healthcheck.py`) la lee.

La conexión de pika no es thread-safe, y el hilo del latido no la puede tocar:

    hilo principal (dueño de pika)               hilo del latido (cada 10 s)
    process_data_events(time_limit=1)            lee HealthState: si un reporte tiene
    HealthState.report("rabbitmq", "ok") ──▶       más de 30 s, esa dependencia es "error"
                                                 corre los checks thread-safe (ping a Mongo)
                                                 escribe /tmp/health.json

Si el dueño de una conexión deja de reportar (está colgado, o trabajando sin atender
la conexión), su dependencia pasa a "error" a los 30 s. Es el mismo plazo del heartbeat
AMQP: pasado ese tiempo sin atender la conexión, el broker la corta de todos modos.

El hilo del latido solo informa: nunca decide terminar el proceso (D14).
"""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from dcicflix_common import health

HEALTH_FILE = Path("/tmp/health.json")
INTERVAL = 10.0
# Edad máxima de la nota para el healthcheck, y de un reporte para el latido.
MAX_AGE = 30.0

log = logging.getLogger(__name__)


class HealthState:
    """Lo que reportan los hilos dueños de cada conexión, con la hora del reporte."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._reports: dict[str, tuple[str, float]] = {}

    def report(self, name: str, status: str) -> None:
        with self._lock:
            self._reports[name] = (status, self._clock())

    def snapshot(self, names: tuple[str, ...], max_age: float = MAX_AGE) -> dict[str, str]:
        """Estado de cada dependencia; "error" si nunca se reportó o el reporte venció."""
        now = self._clock()
        with self._lock:
            reports = dict(self._reports)
        result = {}
        for name in names:
            status, at = reports.get(name, (health.ERROR, float("-inf")))
            result[name] = status if now - at <= max_age else health.ERROR
        return result


class Heartbeat:
    """Escribe el estado del servicio en un archivo, cada `interval` segundos.

    reported: dependencias que reporta otro hilo en `state` (las que no son thread-safe).
    checks:   dependencias que el latido comprueba por sí mismo; cada check lanza una
              excepción si la dependencia no responde.
    """

    def __init__(
        self,
        service: str,
        state: HealthState,
        *,
        reported: tuple[str, ...] = (),
        checks: dict[str, Callable[[], None]] | None = None,
        path: Path = HEALTH_FILE,
        interval: float = INTERVAL,
    ):
        self.service = service
        self.state = state
        self.reported = reported
        self.checks = checks or {}
        self.path = path
        self.interval = interval
        self._last_dependencies: dict[str, str] | None = None

    def start(self) -> None:
        # Un reinicio de Docker conserva /tmp: una nota vieja con "ok" daría healthy
        # antes de que este proceso compruebe nada.
        self.path.unlink(missing_ok=True)
        threading.Thread(target=self._run, name="heartbeat", daemon=True).start()

    def beat(self) -> dict:
        """Un latido: arma el estado y lo escribe. Devuelve lo escrito."""
        dependencies = self.state.snapshot(self.reported)
        errors = {}
        for name, check in self.checks.items():
            try:
                check()
                dependencies[name] = health.OK
            except Exception as exc:  # cualquier falla del check es "no responde"
                dependencies[name] = health.ERROR
                errors[name] = f"{type(exc).__name__}: {exc}"
        data = health.report(self.service, dependencies)
        data["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._write(data)
        self._log_changes(dependencies, errors)
        return data

    def _run(self) -> None:
        while True:
            try:
                self.beat()
            except Exception:
                # Si el latido no puede escribir, la nota vence y el servicio queda unhealthy.
                log.exception("no se pudo escribir el latido")
            time.sleep(self.interval)

    def _write(self, data: dict) -> None:
        # Escritura atómica: el healthcheck nunca lee un archivo a medio escribir.
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.path)

    def _log_changes(self, dependencies: dict[str, str], errors: dict[str, str]) -> None:
        # Solo los cambios: con Mongo caído, un warning por latido sería ruido.
        if dependencies == self._last_dependencies:
            return
        first_beat = self._last_dependencies is None
        self._last_dependencies = dict(dependencies)
        failing = [name for name, status in dependencies.items() if status != health.OK]
        if not failing:
            log.info("latido: ok %s", dependencies)
            return
        if first_beat:
            # El primer latido sale antes de que el hilo principal termine de conectar.
            log.info("latido: arrancando, esperando %s", ", ".join(failing))
            return
        details = "; ".join(f"{name}: {errors.get(name, 'sin reporte reciente')}" for name in failing)
        log.warning("latido: error (%s)", details[:500])
