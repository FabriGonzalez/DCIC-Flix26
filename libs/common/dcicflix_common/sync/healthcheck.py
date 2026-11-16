"""Healthcheck de los workers: lo ejecuta Docker (D13).

    python -m dcicflix_common.sync.healthcheck

Termina con 0 si la nota del latido existe, dice "ok" y tiene menos de 30 s.
Si no, termina con 1 e imprime el motivo, que queda en `docker inspect` (State.Health.Log).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dcicflix_common import health
from dcicflix_common.sync.heartbeat import HEALTH_FILE, MAX_AGE


def problem(path: Path = HEALTH_FILE, max_age: float = MAX_AGE, now: datetime | None = None) -> str | None:
    """El motivo por el que el servicio no está sano, o None si está sano."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"no hay latido: falta {path}"
    except (OSError, ValueError) as exc:
        return f"latido ilegible: {exc}"
    try:
        written = datetime.fromisoformat(data["time"])
    except (KeyError, TypeError, ValueError):
        return "latido sin hora válida"
    age = ((now or datetime.now(timezone.utc)) - written).total_seconds()
    if age > max_age:
        return f"latido vencido: escrito hace {age:.0f} s (máximo {max_age:.0f} s)"
    if data.get("status") != health.OK:
        return f"estado {data.get('status')!r}: {data.get('dependencies')}"
    return None


def main() -> int:
    reason = problem()
    if reason:
        print(reason)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
