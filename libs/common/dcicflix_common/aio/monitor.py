"""Monitor de salud de los servicios HTTP (D12).

Una tarea de fondo revisa las dependencias cada 10 s y guarda el resultado (la "foto").
`GET /health` devuelve esa foto sin chequear nada en el momento: responder es
instantáneo y no le cuesta nada a Mongo ni a Rabbit, consulte quien consulte.

    monitor (cada 10 s): corre los checks en paralelo, cada uno con timeout
          │
          ▼
    foto {status, dependencies, info, time}  ◀── response(): 200 si ok, 503 si no
                                                 503 también si la foto tiene más de 30 s

Un check es una corrutina que lanza una excepción si la dependencia no responde.
Las excepciones de `fatal` son irrecuperables (D14): el monitor llama a `on_fatal` y
termina, y el servicio decide cómo apagarse.

Sin dependencias externas: se prueba en el host sin instalar nada.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from dcicflix_common import health

Check = Callable[[], Awaitable[None]]

INTERVAL = 10.0
MAX_AGE = 30.0
CHECK_TIMEOUT = 5.0

log = logging.getLogger(__name__)


class HealthMonitor:
    def __init__(
        self,
        service: str,
        *,
        critical: dict[str, Check],
        info: dict[str, Check] | None = None,
        fatal: tuple[type[BaseException], ...] = (),
        on_fatal: Callable[[BaseException], None] | None = None,
        interval: float = INTERVAL,
        max_age: float = MAX_AGE,
        check_timeout: float = CHECK_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.service = service
        self.critical = critical
        self.info = info or {}
        self.fatal = fatal
        self.on_fatal = on_fatal
        self.interval = interval
        self.max_age = max_age
        self.check_timeout = check_timeout
        self._clock = clock
        self._snapshot: dict | None = None
        self._checked_at = 0.0
        self._last_results: dict[str, str] | None = None

    async def run(self) -> None:
        """Chequea cada `interval` segundos hasta un error irrecuperable."""
        while True:
            try:
                await self.check_once()
            except self.fatal as exc:
                if self.on_fatal:
                    self.on_fatal(exc)
                return
            except Exception:
                # Si el monitor falla, la foto envejece y /health pasa a 503 a los 30 s.
                log.exception("falló el monitor de salud")
            await asyncio.sleep(self.interval)

    async def check_once(self) -> dict:
        """Corre todos los checks en paralelo y guarda la foto. Devuelve la foto."""
        names = [*self.critical, *self.info]
        checks = [*self.critical.values(), *self.info.values()]
        outcomes = await asyncio.gather(*(self._run(check) for check in checks))
        results = dict(zip(names, (status for status, _ in outcomes)))
        errors = {name: error for name, (_, error) in zip(names, outcomes) if error}

        snapshot = health.report(
            self.service,
            {name: results[name] for name in self.critical},
            {name: results[name] for name in self.info},
        )
        snapshot["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._snapshot = snapshot
        self._checked_at = self._clock()
        self._log_changes(results, errors)
        return snapshot

    def response(self) -> tuple[int, dict]:
        """Lo que responde GET /health: código HTTP y cuerpo."""
        if self._snapshot is None:
            body = health.report(
                self.service,
                dict.fromkeys(self.critical, health.ERROR),
                dict.fromkeys(self.info, health.ERROR),
            )
            body["detail"] = "arrancando: todavía no hay un chequeo"
            return 503, body
        age = self._clock() - self._checked_at
        if age > self.max_age:
            body = {**self._snapshot, "status": health.ERROR}
            body["detail"] = f"estado vencido: el último chequeo fue hace {age:.0f} s"
            return 503, body
        return (200 if self._snapshot["status"] == health.OK else 503), self._snapshot

    async def _run(self, check: Check) -> tuple[str, str | None]:
        try:
            await asyncio.wait_for(check(), self.check_timeout)
        except self.fatal:
            raise
        except Exception as exc:  # cualquier falla del check es "no responde"
            message = str(exc).splitlines()[0] if str(exc) else ""
            return health.ERROR, f"{type(exc).__name__}: {message}" if message else type(exc).__name__
        return health.OK, None

    def _log_changes(self, results: dict[str, str], errors: dict[str, str]) -> None:
        # Solo los cambios: con Mongo caído, un warning cada 10 s sería ruido.
        if results == self._last_results:
            return
        first_check = self._last_results is None
        self._last_results = dict(results)
        failing = [name for name, status in results.items() if status != health.OK]
        if not failing:
            log.info("salud: ok %s", results)
            return
        if first_check:
            # El primer chequeo corre mientras las conexiones todavía se están abriendo.
            log.info("salud: arrancando, esperando %s", ", ".join(failing))
            return
        details = "; ".join(f"{name}: {errors.get(name, '?')}" for name in failing)[:500]
        if any(name in self.critical for name in failing):
            log.warning("salud: error (%s)", details)
        else:
            # Las informativas no cambian el status (D12): el servicio sigue sano.
            log.warning("salud: ok, con informativas en error (%s)", details)
