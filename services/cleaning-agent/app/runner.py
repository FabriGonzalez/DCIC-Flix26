"""Orden de la limpieza contra la base, con la marca de limpieza.

    sin marca / pending ──▶ running ──▶ copia cruda ──▶ limpia y escribe ──▶ done
                              ▲                                    │
                              └──── caída: al reiniciar, se repite ┘

La marca guarda además:
- rawCopied: la copia cruda está completa. Desde ahí nunca se vuelve a copiar, porque
  movies y reviews pueden estar a medio limpiar.
- eventPublished: si ya salió data.cleaned (patrón outbox). Lo publica el hilo dueño
  de la conexión de Rabbit, no este módulo.
"""

import logging
import time

from pymongo.database import Database

from app import store
from app.pipeline import clean

log = logging.getLogger(__name__)


def runCleaning(db: Database) -> None:
    """Limpia si la marca no dice done. Repetible: tras una caída, se vuelve a llamar."""
    state = store.readState(db)
    if state["status"] == store.DONE:
        log.info("marca done: la limpieza ya se hizo")
        return
    if state["status"] == store.RUNNING:
        log.warning("marca running: la limpieza anterior se cortó; se repite desde la copia cruda")

    started = time.monotonic()
    store.updateState(db, status=store.RUNNING, startedAt=store.now(), eventPublished=False)
    if not state.get("rawCopied"):
        store.copyRaw(db)
        store.updateState(db, rawCopied=True)

    movies, reviews = store.readRaw(db)
    result = clean(movies, reviews, datasetCreated(reviews))
    store.replaceDocuments(db, store.MOVIES, result.movies)
    store.replaceDocuments(db, store.REVIEWS, result.reviews)
    store.writeAudit(db, store.MOVIES, result.movieChanges)
    store.writeAudit(db, store.REVIEWS, result.reviewChanges)

    store.updateState(db, status=store.DONE, finishedAt=store.now(), eventPublished=False)
    log.info(
        "limpieza terminada en %.0f s: %d películas y %d reseñas con cambios",
        time.monotonic() - started,
        len(result.movieChanges),
        len(result.reviewChanges),
    )


def datasetCreated(reviews: list[dict]):
    """Creación del dataset: el ObjectId más antiguo de las reseñas (ANOMALIAS, B10)."""
    return min(r["_id"].generation_time for r in reviews).replace(tzinfo=None)


def eventPending(db: Database) -> bool:
    state = store.readState(db)
    return state["status"] == store.DONE and not state.get("eventPublished")


def markEventPublished(db: Database) -> None:
    store.updateState(db, eventPublished=True)
