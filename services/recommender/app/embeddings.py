"""Caché de embeddings del plot, por hash del texto (R17, docs/recomendador.md 4.4).

    hash SHA-256 del plot ──▶ fila de `vectors` (float32, 384 columnas)

La clave es el texto y no el `_id`: al fusionar duplicados, la película que queda puede
tener el plot de otra copia (ANOMALIAS, A5). Como se embeben los plots de todas las
copias, el plot de la ganadora siempre está.

El archivo vive en el volumen `recommender-cache`, así que el segundo arranque no vuelve
a embeber. Se escribe en un temporal y se renombra: un corte a mitad de la escritura deja
el archivo anterior entero. Se guarda cada SAVE_EVERY plots, así que un reinicio a mitad
del embedding pierde como mucho esa cantidad.

Todo es bloqueante (disco y ONNX): se llama desde un hilo, nunca desde el event loop.
"""

import hashlib
import logging
import os
import threading
import time
from pathlib import Path

import numpy as np

from app import model

log = logging.getLogger(__name__)

CACHE_FILE = "plots.npz"
BATCH_SIZE = 256  # el de la medición de 4.4
SAVE_EVERY = 2048  # ≈ 40 s de embedding con 4 CPUs


def plot_hash(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


class Stopped(Exception):
    """Se pidió detener el servicio a mitad del embedding."""


class PlotEmbeddings:
    def __init__(self, cache_dir: Path, *, stop: threading.Event | None = None):
        self.path = cache_dir / CACHE_FILE
        self._stop = stop or threading.Event()
        self._lock = threading.Lock()  # embeber y leer pueden venir de hilos distintos
        self._hashes: list[bytes] = []
        self._rows: dict[bytes, int] = {}
        self._vectors = np.empty((0, model.DIM), np.float32)

    def __len__(self) -> int:
        return len(self._hashes)

    def load(self) -> None:
        """Carga el archivo del volumen. Si no existe o no sirve, arranca vacía."""
        if not self.path.exists():
            log.info("sin caché de embeddings en %s: se embeben todos los plots", self.path)
            return
        try:
            with np.load(self.path) as data:
                name, hashes, vectors = str(data["model"]), data["hashes"], data["vectors"]
        except Exception as exc:  # truncado o corrupto: se recalcula, no es irrecuperable
            log.warning("caché de embeddings ilegible (%s: %s): se embebe de nuevo", type(exc).__name__, exc)
            return
        if name != model.NAME:
            log.warning("la caché es del modelo %s y el actual es %s: se embebe de nuevo", name, model.NAME)
            return
        if hashes.dtype != np.uint8 or hashes.shape != (len(vectors), 32) or vectors.shape[1:] != (model.DIM,):
            log.warning("caché de embeddings con formato inesperado: se embebe de nuevo")
            return
        self._hashes = [row.tobytes() for row in hashes]
        self._rows = {h: i for i, h in enumerate(self._hashes)}
        self._vectors = vectors.astype(np.float32, copy=False)
        log.info("caché de embeddings: %d vectores en %s", len(self), self.path)

    def save(self) -> None:
        tmp = self.path.with_name("plots.tmp.npz")  # savez agrega ".npz" si falta
        # Los hashes como matriz de bytes (n × 32), no como dtype "S32": numpy recorta los
        # \x00 del final al leer un "S32", y 1 de cada 256 digests termina en \x00 (medido
        # en P1: 78 plots se volvían a embeber en cada arranque).
        hashes = np.frombuffer(b"".join(self._hashes), np.uint8).reshape(-1, 32)
        np.savez(tmp, model=np.array(model.NAME), hashes=hashes, vectors=self._vectors)
        os.replace(tmp, self.path)  # atómico en el mismo sistema de archivos

    def missing(self, texts: list[str]) -> list[str]:
        """Los textos sin vector, sin repetir y en orden."""
        seen: set[bytes] = set()
        result = []
        for text in texts:
            key = plot_hash(text)
            if key not in self._rows and key not in seen:
                seen.add(key)
                result.append(text)
        return result

    def embed_missing(self, texts: list[str]) -> int:
        """Embebe los textos que falten y guarda la caché. Devuelve cuántos embebió.

        Lanza Stopped si se pidió detener: lo ya embebido queda guardado.
        """
        with self._lock:
            todo = self.missing(texts)
            if not todo:
                return 0
            # El modelo se carga solo para embeber y se suelta al terminar: después del
            # arranque inicial casi no se usa, y cargado ocupa ≈ 1 GB (medido en P1).
            embedder = model.load()
            started = time.monotonic()
            log.info("embebiendo %d plots", len(todo))
            for start in range(0, len(todo), SAVE_EVERY):
                chunk = todo[start : start + SAVE_EVERY]
                done = self._embed(embedder, chunk)
                self._add(chunk[: len(done)], done)
                self.save()
                elapsed = time.monotonic() - started
                log.info("embebidos %d de %d plots (%.0f s)", start + len(done), len(todo), elapsed)
                if len(done) < len(chunk):
                    raise Stopped
            return len(todo)

    def vector(self, text: str) -> np.ndarray | None:
        row = self._rows.get(plot_hash(text))
        return None if row is None else self._vectors[row]

    def _embed(self, embedder, texts: list[str]) -> np.ndarray:
        # fastembed calcula de a un lote cuando se le pide el siguiente vector: entre lote
        # y lote se mira el pedido de parada, así detener tarda un lote (≈ 5 s), no un chunk.
        vectors = []
        for i, vector in enumerate(embedder.embed(texts, batch_size=BATCH_SIZE)):
            vectors.append(vector)
            if (i + 1) % BATCH_SIZE == 0 and self._stop.is_set():
                break
        return np.array(vectors, dtype=np.float32).reshape(-1, model.DIM)

    def _add(self, texts: list[str], vectors: np.ndarray) -> None:
        for text in texts:
            key = plot_hash(text)
            self._rows[key] = len(self._hashes)
            self._hashes.append(key)
        self._vectors = np.concatenate([self._vectors, vectors])
