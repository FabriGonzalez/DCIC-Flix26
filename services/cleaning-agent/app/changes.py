"""Registro de cambios que producen las reglas.

Las reglas no escriben la auditoría: devuelven la lista de cambios y quien las llama
decide dónde guardarla. Así siguen siendo funciones puras y se testean sin Mongo.
"""

from dataclasses import dataclass
from typing import Any

# Distingue "el campo no existía" de "el campo valía None".
MISSING = object()


@dataclass(frozen=True)
class Change:
    field: str  # ruta con puntos, por ejemplo "imdb.rating"
    rule: str  # código de ANOMALIAS, por ejemplo "P2"
    before: Any
    after: Any
    note: str | None = None


def getPath(doc: dict, path: str) -> Any:
    """Valor en la ruta con puntos, o MISSING si algún tramo no existe."""
    value: Any = doc
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return MISSING
        value = value[key]
    return value


def setPath(doc: dict, path: str, value: Any, rule: str, changes: list[Change]) -> None:
    """Asigna el valor y registra el cambio solo si cambia de verdad.

    '1989' → 1989 es un cambio. 7 → 7.0 se asigna (el contrato pide double) pero no se
    registra: el dato es el mismo.
    """
    before = getPath(doc, path)
    *parents, last = path.split(".")
    target = doc
    for key in parents:
        target = target.setdefault(key, {})
    target[last] = value
    if before is MISSING or not _same(before, value):
        changes.append(Change(path, rule, None if before is MISSING else before, value))


def _same(a: Any, b: Any) -> bool:
    numbers = (int, float)
    if isinstance(a, numbers) and isinstance(b, numbers) and not isinstance(a, bool) and not isinstance(b, bool):
        return a == b
    return type(a) is type(b) and a == b
