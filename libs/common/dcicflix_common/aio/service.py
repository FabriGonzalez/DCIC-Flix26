"""Conexiones y salud de un servicio async: el stub "conectado" (D1) de backend y recommender.

Sin framework web (D9): el servicio pone el servidor HTTP y la ruta /health.

    start():  tarea "connect"  → Mongo y Rabbit en paralelo, con reintentos
              tarea "monitor"  → chequea cada 10 s (mongodb, rabbitmq, topology + info)
    health(): la foto del monitor para GET /health

Política ante fallas (D14):
    Mongo o Rabbit no responden   → 503; pymongo y connect_robust se reconectan solos
    credenciales rechazadas       → on_fatal
    topología faltante            → on_fatal
on_fatal la pone el servicio: detiene el servidor y el proceso termina con código 1.
"""

import asyncio
import logging
from collections.abc import Callable

from aio_pika.abc import AbstractRobustConnection

from dcicflix_common.aio import mongo, rabbit
from dcicflix_common.aio.monitor import Check, HealthMonitor
from dcicflix_common.config import MongoSettings, RabbitSettings
from dcicflix_common.errors import TopologyError

log = logging.getLogger(__name__)


class DataService:
    def __init__(
        self,
        service: str,
        *,
        on_fatal: Callable[[BaseException], None],
        info: dict[str, Check] | None = None,
    ):
        self.service = service
        self._mongo_settings = MongoSettings.from_env()
        self._rabbit_settings = RabbitSettings.from_env()
        self._on_fatal = on_fatal
        self.mongo = mongo.client(self._mongo_settings)
        self.rabbit: AbstractRobustConnection | None = None
        self.monitor = HealthMonitor(
            service,
            critical={"mongodb": self._check_mongo, "rabbitmq": self._check_rabbit, "topology": self._check_topology},
            info=info,
            fatal=(TopologyError,),
            on_fatal=on_fatal,
        )
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Arranca la conexión y el monitor en segundo plano: /health responde desde ya."""
        self._tasks = [
            asyncio.create_task(self._connect(), name="connect"),
            asyncio.create_task(self.monitor.run(), name="health-monitor"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.rabbit is not None:
            await self.rabbit.close()
        await self.mongo.close()

    def health(self) -> tuple[int, dict]:
        return self.monitor.response()

    async def _connect(self) -> None:
        try:
            await asyncio.gather(mongo.wait_until_ready(self.mongo), self._connect_rabbit())
            # El primer chequeo del monitor corrió con las conexiones a medio abrir:
            # sin esto, /health daría 503 hasta el siguiente, 10 s después.
            await self.monitor.check_once()
        except Exception as exc:
            # Los errores recuperables se reintentan sin límite: lo que llega acá es irrecuperable.
            self._on_fatal(exc)

    async def _connect_rabbit(self) -> None:
        self.rabbit = await rabbit.connect(self._rabbit_settings, name=self.service)

    async def _check_mongo(self) -> None:
        await mongo.ping(self.mongo)

    async def _check_rabbit(self) -> None:
        # `is_closed` solo indica si se llamó a close(): mientras connect_robust reconecta,
        # sigue en False (comprobado en F4). El estado real es el evento `connected`.
        if self.rabbit is None or not self.rabbit.connected.is_set():
            raise ConnectionError("sin conexión con RabbitMQ")

    async def _check_topology(self) -> None:
        await self._check_rabbit()
        await rabbit.verify_topology(self.rabbit)  # TopologyError: irrecuperable
