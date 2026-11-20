"""Marca de limpieza (README, "Estados del sistema"). SOLO DATOS, como topology.py.

La escribe el cleaning-agent y la leen el backend (GET /status) y el recommender. La forma
es la del cleaning-agent (services/cleaning-agent/app/store.py: STATE, STATE_ID):

    db.cleaning  {_id: "state", status: "pending" | "running" | "done",
                  rawCopied, eventPublished, startedAt, finishedAt}

Que falte el documento equivale a "pending": la limpieza todavía no empezó.
"""

COLLECTION = "cleaning"
DOCUMENT_ID = "state"
STATUS_FIELD = "status"

PENDING = "pending"
RUNNING = "running"
DONE = "done"
STATES = (PENDING, RUNNING, DONE)
