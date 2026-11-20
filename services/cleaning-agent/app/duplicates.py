"""Películas duplicadas: paso 2 de ANOMALIAS (A3–A6, G2).

Trabaja sobre películas que ya pasaron por las reglas de campo: si se fusionara antes,
un '1971è' contaría como "presente" y le ganaría a un 1971 limpio.
"""

import copy
import re
import unicodedata
from collections import defaultdict
from datetime import datetime

from app.changes import Change, setPath

DUPLICATE_MOVIE = "duplicateMovie"

# num_mflix_comments se recalcula al final (A16): fusionarlo solo ensuciaría la auditoría.
_NOT_MERGED = {"_id", "num_mflix_comments"}


def normalizeTitle(title: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", title)).strip().casefold()


def _peopleKey(values):
    """Clave comparable de una lista de personas, o None si falta o está vacía."""
    return tuple(sorted(v.strip() for v in values)) if isinstance(values, list) and values else None


def _sameMovie(a: dict, b: dict) -> bool:
    """Regla secundaria (A4): mismo título, año y duración, y coinciden directors o cast.

    Sin la evidencia de personas, título + año da 21 falsos positivos (Black Rain, 1989).
    """
    if a.get("runtime") is None or a.get("runtime") != b.get("runtime"):
        return False
    return any(
        _peopleKey(a.get(field)) is not None and _peopleKey(a.get(field)) == _peopleKey(b.get(field))
        for field in ("directors", "cast")
    )


def findDuplicateGroups(movies: list[dict]) -> list[list[dict]]:
    """Grupos de 2 o más copias de la misma película: mismo imdb.id (A3) más los pares de A4."""
    byImdbId: dict = defaultdict(list)
    for movie in movies:
        byImdbId[movie["imdb"]["id"]].append(movie)

    # A4 compara un representante por imdb.id entre los que comparten título y año.
    byTitleYear: dict = defaultdict(list)
    for imdbId, copies in byImdbId.items():
        first = copies[0]
        if first.get("year") is not None:
            byTitleYear[(normalizeTitle(first["title"]), first["year"])].append(imdbId)

    for imdbIds in byTitleYear.values():
        for i, idA in enumerate(imdbIds):
            for idB in imdbIds[i + 1 :]:
                if idA in byImdbId and idB in byImdbId and _sameMovie(byImdbId[idA][0], byImdbId[idB][0]):
                    byImdbId[idA] += byImdbId.pop(idB)

    return [copies for copies in byImdbId.values() if len(copies) > 1]


def _filledFields(movie: dict) -> int:
    return sum(value not in (None, "", [], {}) for value in movie.values())


def _priority(movie: dict):
    """Más reciente primero; si empatan, más campos completos; si siguen, _id mayor (A6)."""
    lastUpdated = movie.get("lastupdated")
    return (lastUpdated if isinstance(lastUpdated, datetime) else datetime.min, _filledFields(movie), movie["_id"])


def _fillMissing(target: dict, source: dict, prefix: str, changes: list[Change]) -> None:
    """Completa en target los campos que faltan o son null, tomándolos de source.

    Entra a los subdocumentos (imdb.rating puede venir de otra copia). Las listas se toman
    enteras: mezclar elencos de dos copias inventaría uno que no existe.
    """
    for key, value in source.items():
        if not prefix and key in _NOT_MERGED:
            continue
        path = f"{prefix}{key}"
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _fillMissing(current, value, f"{path}.", changes)
        elif current is None and value is not None:
            target[key] = copy.deepcopy(value)
            changes.append(Change(path, "A5", None, value))


def mergeCopies(copies: list[dict]) -> tuple[dict, list[Change], list[dict]]:
    """(ganadora fusionada, cambios de la ganadora, perdedoras). No modifica las copias."""
    ordered = sorted(copies, key=_priority, reverse=True)
    winner = copy.deepcopy(ordered[0])
    changes: list[Change] = []
    for other in ordered[1:]:
        _fillMissing(winner, other, "", changes)
    return winner, changes, ordered[1:]


def dedupeMovies(movies: list[dict]) -> tuple[list[dict], dict, dict]:
    """Fusiona los duplicados y marca a todas las películas con deleted y mergedInto.

    Devuelve (películas, cambios por _id, mapa perdedora → ganadora). Todas las películas
    salen con deleted, deletedReason y mergedInto: el campo nunca falta.
    """
    replaced: dict = {}
    changesById: dict = defaultdict(list)
    mergedInto: dict = {}

    for group in findDuplicateGroups(movies):
        winner, changes, losers = mergeCopies(group)
        replaced[winner["_id"]] = winner
        changesById[winner["_id"]] += changes
        for loser in losers:
            mergedInto[loser["_id"]] = winner["_id"]
            changed = copy.copy(loser)
            setPath(changed, "deleted", True, "G2", changesById[loser["_id"]])
            changed["deletedReason"] = DUPLICATE_MOVIE
            changed["mergedInto"] = winner["_id"]
            replaced[loser["_id"]] = changed

    result = []
    for movie in movies:
        doc = replaced.get(movie["_id"]) or copy.copy(movie)
        doc.setdefault("deleted", False)
        doc.setdefault("deletedReason", None)
        doc.setdefault("mergedInto", None)
        result.append(doc)
    return result, dict(changesById), mergedInto
