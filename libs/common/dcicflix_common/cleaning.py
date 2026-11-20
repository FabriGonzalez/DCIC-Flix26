"""Marca de limpieza (README, "Estados del sistema"). SOLO DATOS, como topology.py.

Es el único lugar con estos nombres: la escribe el cleaning-agent y la leen el backend
(GET /status) y el recommender.

    db.system  {_id: "cleaning", state: "pending" | "running" | "done"}

Que falte el documento equivale a "pending": la limpieza todavía no empezó.
"""

COLLECTION = "system"
DOCUMENT_ID = "cleaning"
STATE_FIELD = "state"

PENDING = "pending"
RUNNING = "running"
DONE = "done"
STATES = (PENDING, RUNNING, DONE)
