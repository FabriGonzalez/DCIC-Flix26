"""Lectura y escritura en Mongo: copia cruda, documentos limpios, auditoría y marca.

Toda escritura es repetible: correrla dos veces deja la base igual que una. Así, si el
agente se cae a mitad, al reiniciar repite todo desde la copia cruda (ANOMALIAS, sección 7).
"""

from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime, timezone

from pymongo import ReplaceOne
from pymongo.database import Database

from app.changes import Change

MOVIES = "movies"
REVIEWS = "reviews"
RAW = {MOVIES: "moviesRaw", REVIEWS: "reviewsRaw"}
AUDIT = "audit"
STATE = "cleaning"
STATE_ID = "state"

# Valores de la marca (README, "Estado del sistema"). Sin documento equivale a pending.
PENDING, RUNNING, DONE = "pending", "running", "done"

_BATCH = 1000


def readState(db: Database) -> dict:
    return db[STATE].find_one({"_id": STATE_ID}) or {"_id": STATE_ID, "status": PENDING}


def updateState(db: Database, **fields) -> None:
    db[STATE].update_one({"_id": STATE_ID}, {"$set": fields}, upsert=True)


def copyRaw(db: Database) -> None:
    """Copia movies y reviews a sus colecciones Raw.

    $out escribe en una colección temporal y la renombra al final: si se corta a mitad,
    la copia anterior (o su ausencia) queda intacta.
    """
    for name, raw in RAW.items():
        db[name].aggregate([{"$match": {}}, {"$out": raw}])


def readRaw(db: Database) -> tuple[list[dict], list[dict]]:
    return list(db[RAW[MOVIES]].find()), list(db[RAW[REVIEWS]].find())


def replaceDocuments(db: Database, name: str, docs: Iterable[dict]) -> None:
    """Reemplaza cada documento por _id. Repetirlo no cambia nada."""
    _bulkReplace(db, name, docs)


def writeAudit(db: Database, collection: str, changesById: dict[object, list[Change]]) -> None:
    """Un registro por documento, con el mismo _id y sus cambios en orden."""
    records = (
        {"_id": docId, "collection": collection, "changes": [asdict(c) for c in changes]}
        for docId, changes in changesById.items()
    )
    _bulkReplace(db, AUDIT, records)


def _bulkReplace(db: Database, name: str, docs: Iterable[dict]) -> None:
    batch = []
    for doc in docs:
        batch.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
        if len(batch) == _BATCH:
            db[name].bulk_write(batch, ordered=False)
            batch = []
    if batch:
        db[name].bulk_write(batch, ordered=False)


def now() -> datetime:
    # Mongo guarda UTC; pymongo devuelve fechas sin zona, igual que las del dataset.
    return datetime.now(timezone.utc).replace(tzinfo=None)
