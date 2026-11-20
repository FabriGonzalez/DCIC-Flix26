"""Ciclo de vida del recommender (docs/recomendador.md 9.2).

    start() ─▶ tarea "embed": espera a Mongo → lee los plots crudos → los embebe en un hilo
                              (sin esperar data.cleaned: la limpieza no toca plot, R17)

`phase` dice qué falta para estar listo, y `/health` la muestra junto con `ready`:

    embedding → waiting-cleaning → (indexing → ready: P3)

Regla del event loop: leer de Mongo es async; embeber es CPU y disco y va en un hilo
(run_in_executor). Así /health y el heartbeat de Rabbit siguen respondiendo.
"""

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from dcicflix_common.aio import mongo as aio_mongo

from app.embeddings import PlotEmbeddings, Stopped

log = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("RECOMMENDER_CACHE_DIR", "/cache"))
_RETRY_DELAY = 5.0


class Recommender:
    def __init__(self, mongo: AsyncMongoClient, *, on_fatal: Callable[[BaseException], None]):
        self._mongo = mongo
        self._on_fatal = on_fatal
        self._stop = threading.Event()  # para el hilo: las tareas se cancelan, los hilos no
        self.embeddings = PlotEmbeddings(CACHE_DIR, stop=self._stop)
        self.phase = "embedding"
        self._tasks: list[asyncio.Task] = []

    @property
    def ready(self) -> bool:
        return self.phase == "ready"

    def state(self) -> dict:
        return {"ready": self.ready, "phase": self.phase}

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._embed_plots(), name="embed")]

    async def stop(self) -> None:
        self._stop.set()  # el hilo que embebe termina el lote en curso y guarda
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _embed_plots(self) -> None:
        try:
            await asyncio.to_thread(self.embeddings.load)
            plots = await self._read_plots()
            added = await asyncio.to_thread(self.embeddings.embed_missing, plots)
            log.info("embeddings listos: %d plots distintos, %d embebidos ahora", len(self.embeddings), added)
            self.phase = "waiting-cleaning"
        except (Stopped, asyncio.CancelledError):
            pass
        except Exception as exc:  # modelo faltante, volumen sin permisos: no se arregla reintentando
            self._on_fatal(exc)

    async def _read_plots(self) -> list[str]:
        """Los plots de todas las películas, activas o no (R17). Reintenta si Mongo se cae."""
        await aio_mongo.wait_until_ready(self._mongo)
        movies = self._mongo.get_default_database().movies
        while True:
            try:
                cursor = movies.find({}, {"_id": 0, "plot": 1})
                plots = [doc["plot"] async for doc in cursor if _is_text(doc.get("plot"))]
            except PyMongoError as exc:
                log.warning("no pude leer los plots (%s); reintento en %.0f s", type(exc).__name__, _RETRY_DELAY)
                await asyncio.sleep(_RETRY_DELAY)
            else:
                log.info("leídos %d plots de MongoDB", len(plots))
                return plots


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
