"""Ciclo de vida del recommender (docs/recomendador.md 9.2; README, "Estados del sistema").

    start()
     ├─ "embed"     carga la caché → lee los plots crudos → embebe los que faltan
     │              (sin esperar data.cleaned: la limpieza no toca plot, R17)
     ├─ "cleaning"  se suscribe a recommender.data-cleaned → lee la marca de limpieza
     │              marca done o mensaje en la cola → pide un indexado
     ├─ "index"     espera el pedido y los embeddings → lee películas y votos → indexa
     └─ "wr"        cada 60 s, con el catálogo vigente: votos activos → WR y rankings (R18)

Se suscribe ANTES de leer la marca: si la limpieza termina entre los dos pasos, el
mensaje queda en la cola y no se pierde. El mensaje es solo un aviso, no se lee su
contenido: lo que vale es la marca. Por eso se confirma al llegar: si el proceso se cae
indexando, al volver lee la marca done e indexa igual.

Los pedidos se juntan: la marca done más un mensaje viejo en la cola durable, o varios
mensajes seguidos, dan un indexado (uno más si llegan mientras indexa).

`ready` es "hay un índice para responder"; `phase`, qué está haciendo:

    embedding → waiting-cleaning → indexing → ready      (reindexando: ready e indexing)

Cada índice nuevo reemplaza al anterior en una sola asignación (`self.index`), así que
una petición ve siempre un catálogo y su calidad juntos.

Regla del event loop: leer de Mongo es async; embeber e indexar es CPU y va en un hilo
(asyncio.to_thread). Así /health y el heartbeat de Rabbit siguen respondiendo.
"""

import asyncio
import logging
import os
import threading
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from aio_pika.abc import AbstractIncomingMessage
from pymongo.errors import PyMongoError

from dcicflix_common import cleaning, topology
from dcicflix_common.aio import mongo as aio_mongo
from dcicflix_common.aio.service import DataService

from app import model, params, store
from app.embeddings import PlotEmbeddings, Stopped
from app.index import Catalog, Quality, build_catalog, build_quality

log = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("RECOMMENDER_CACHE_DIR", "/cache"))
_RETRY_DELAY = 5.0

EMBEDDING, WAITING_CLEANING, INDEXING, READY = "embedding", "waiting-cleaning", "indexing", "ready"


@dataclass(frozen=True)
class Index:
    catalog: Catalog
    quality: Quality


class Recommender:
    def __init__(self, data: DataService, *, on_fatal: Callable[[BaseException], None]):
        self._data = data
        self.db = data.mongo.get_default_database()
        self._on_fatal = on_fatal
        self._stop = threading.Event()  # para los hilos: las tareas se cancelan, los hilos no
        self.embeddings = PlotEmbeddings(CACHE_DIR, stop=self._stop)
        self.index: Index | None = None
        self._embedded = asyncio.Event()
        self._index_requested = asyncio.Event()
        self._indexing = False
        self._tasks: list[asyncio.Task] = []

    @property
    def ready(self) -> bool:
        return self.index is not None

    @property
    def phase(self) -> str:
        if self._indexing:
            return INDEXING
        if self.index is not None:
            return READY
        return WAITING_CLEANING if self._embedded.is_set() else EMBEDDING

    def state(self) -> dict:
        index = self.index
        return {
            "ready": self.ready,
            "phase": self.phase,
            "movies": None if index is None else len(index.catalog),
            "votes": None if index is None else index.quality.votes,
        }

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._guard(self._embed_plots()), name="embed"),
            asyncio.create_task(self._guard(self._watch_cleaning()), name="cleaning"),
            asyncio.create_task(self._guard(self._index_loop()), name="index"),
            asyncio.create_task(self._guard(self._refresh_wr()), name="wr"),
        ]

    async def stop(self) -> None:
        self._stop.set()  # el hilo que embebe termina el lote en curso y guarda
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _guard(self, work: Awaitable[None]) -> None:
        """Lo que llega acá no se arregla reintentando (D14): modelo faltante, volumen sin
        permisos, topología faltante, un bug. Los errores de Mongo se reintentan antes."""
        try:
            await work
        except (Stopped, asyncio.CancelledError):
            pass
        except Exception as exc:
            self._on_fatal(exc)

    # --- Embeddings -------------------------------------------------------------------

    async def _embed_plots(self) -> None:
        await asyncio.to_thread(self.embeddings.load)
        await aio_mongo.wait_until_ready(self._data.mongo)
        plots = await self._retry("los plots", lambda: store.read_all_plots(self.db))
        texts = [plot for plot in plots if _is_text(plot)]
        log.info("leídos %d plots de MongoDB", len(texts))
        added = await asyncio.to_thread(self.embeddings.embed_missing, texts)
        log.info("embeddings listos: %d plots distintos, %d embebidos ahora", len(self.embeddings), added)
        self._embedded.set()

    # --- Limpieza ---------------------------------------------------------------------

    async def _watch_cleaning(self) -> None:
        rabbit = await self._data.wait_connected()
        channel = await rabbit.channel()
        await channel.set_qos(prefetch_count=1)
        # Pasiva: la cola la declara topology-init. Igual queda registrada en el canal
        # robusto, que la vuelve a declarar y restaura el consumidor si Rabbit se reconecta.
        queue = await channel.declare_queue(topology.RECOMMENDER_DATA_CLEANED_QUEUE, passive=True)
        await queue.consume(self._on_data_cleaned)
        log.info("suscripto a %s", queue.name)

        state = await self._retry("la marca de limpieza", lambda: store.read_flag(self.db))
        if state == cleaning.DONE:
            self._request_index("marca de limpieza done")
        elif state in cleaning.STATES or state is None:
            log.info("marca de limpieza %s: espero data.cleaned", state or "ausente")
        else:
            log.warning("marca de limpieza con estado desconocido %r: espero data.cleaned", state)

    async def _on_data_cleaned(self, message: AbstractIncomingMessage) -> None:
        await message.ack()
        self._request_index("mensaje de data.cleaned")

    def _request_index(self, reason: str) -> None:
        if not self._embedded.is_set():
            log.info("%s: indexo cuando terminen los embeddings", reason)
        elif self._indexing:
            log.info("%s: indexo de nuevo al terminar el indexado en curso", reason)
        else:
            log.info("%s: indexo", reason)
        self._index_requested.set()

    # --- Índice -----------------------------------------------------------------------

    async def _index_loop(self) -> None:
        while True:
            await self._index_requested.wait()
            await self._embedded.wait()
            self._index_requested.clear()  # lo que llegue desde acá pide otro indexado
            self._indexing = True
            try:
                await self._build_index()
            finally:
                self._indexing = False

    async def _build_index(self) -> None:
        started = time.monotonic()
        movies = await self._retry("las películas activas", lambda: store.read_movies(self.db))
        if not movies:
            log.warning("no hay películas con deleted: false; no indexo y espero otro data.cleaned")
            return
        plots = [doc.get("plot") for doc in movies]
        added = await asyncio.to_thread(self.embeddings.embed_missing, [p for p in plots if _is_text(p)])
        vectors = await asyncio.to_thread(self._plot_vectors, plots)
        t_read = time.monotonic()
        catalog = await asyncio.to_thread(build_catalog, movies, vectors)
        t_catalog = time.monotonic()
        votes = await self._retry("los votos", lambda: store.read_vote_totals(self.db, catalog))
        quality = await asyncio.to_thread(build_quality, catalog, votes.counts, votes.sums)
        self.index = Index(catalog, quality)
        done = time.monotonic()
        log.info(
            "índice listo: %d películas, %d géneros, %d votos, %d plots embebidos ahora | "
            "lectura %.1f s, catálogo %.1f s, votos y WR %.1f s, total %.1f s",
            len(catalog), len(catalog.genres), quality.votes, added,
            t_read - started, t_catalog - t_read, done - t_catalog, done - started,
        )
        _log_quality(quality)
        _log_anomalies(catalog.anomalies + votes.anomalies)

    def _plot_vectors(self, plots: list) -> np.ndarray:
        """Una fila por película; de ceros si no tiene plot (R16)."""
        vectors = np.zeros((len(plots), model.DIM), np.float32)
        for i, plot in enumerate(plots):
            if _is_text(plot):
                vectors[i] = self.embeddings.vector(plot)
        return vectors

    # --- WR cada 60 s -----------------------------------------------------------------

    async def _refresh_wr(self) -> None:
        while True:
            await asyncio.sleep(params.WR_REFRESH)
            index = self.index
            if index is None:
                continue
            try:
                votes = await store.read_vote_totals(self.db, index.catalog)
            except PyMongoError as exc:
                log.warning("no pude recalcular el WR (%s); sigo con el anterior", type(exc).__name__)
                continue
            quality = await asyncio.to_thread(build_quality, index.catalog, votes.counts, votes.sums)
            if self.index is not index:
                continue  # se reindexó mientras tanto: este WR es del catálogo anterior
            self.index = Index(index.catalog, quality)
            if quality.votes != index.quality.votes:
                log.info("WR recalculado: %d votos (antes %d)", quality.votes, index.quality.votes)
                _log_quality(quality)

    # --- Reintentos -------------------------------------------------------------------

    async def _retry(self, what: str, read: Callable[[], Awaitable]):
        """Reintenta mientras Mongo no responda: se reconecta solo."""
        while True:
            try:
                return await read()
            except PyMongoError as exc:
                log.warning("no pude leer %s (%s); reintento en %.0f s", what, type(exc).__name__, _RETRY_DELAY)
                await asyncio.sleep(_RETRY_DELAY)


def _log_quality(quality: Quality) -> None:
    q5 = "sin Q" if quality.q5 is None else "Q₅ = {:.2f}·Q {:+.2f}".format(*quality.q5)
    log.info("WR: C %.3f, %s, media %.2f, desvío %.2f", quality.mean_vote, q5, quality.wr.mean(), quality.wr.std())


def _log_anomalies(anomalies: Counter) -> None:
    if anomalies:
        log.warning("valores fuera de contrato, descartados: %s", dict(sorted(anomalies.items())))
    else:
        log.info("valores fuera de contrato: ninguno")


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
