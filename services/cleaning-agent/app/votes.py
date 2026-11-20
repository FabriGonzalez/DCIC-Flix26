"""Reseñas entre documentos: pasos 3 a 6 de ANOMALIAS (G2, B13, B4, B11, B12, B7, B8, A16).

Recibe películas ya deduplicadas y reseñas que ya pasaron por las reglas de campo.
Cada reseña descartada tiene un solo motivo: el de la primera regla que la descarta.
"""

import copy
from collections import Counter, defaultdict
from datetime import datetime

from app.changes import Change, setPath
from app.reviews import UPDATE_PREFIX, isAnonymous, isUsefulComment

ANONYMOUS = "anonymous"
ORPHAN = "orphan"
DUPLICATE_VOTE = "duplicateVote"
NO_CONTENT = "noContent"


def _softDelete(review: dict, reason: str, rule: str, changes: list[Change]) -> None:
    setPath(review, "deleted", True, rule, changes)
    review["deletedReason"] = reason


def _validDate(review: dict, released) -> datetime | None:
    """Fecha que cuenta para B13: conocida y no anterior al estreno.

    Las futuras ya quedaron en null (B10) y las 'circa N' valen 1/1/N (B9).
    """
    date = review.get("date")
    if date is None or (isinstance(released, datetime) and date < released):
        return None
    return date


def _isUpdate(review: dict) -> bool:
    return isinstance(review.get("comment"), str) and review["comment"].startswith(UPDATE_PREFIX)


def pickWinnerVote(votes: list[dict], released) -> dict:
    """Voto que se queda entre varios del mismo usuario y película (B13).

    En orden: tiene fecha válida, la fecha más reciente, es un "Update", el _id mayor.
    No se mezclan votos: tomar el rating de uno y el comentario de otro inventaría una
    reseña que nadie escribió.
    """

    def key(review):
        date = _validDate(review, released)
        return (date is not None, date or datetime.min, _isUpdate(review), review["_id"])

    return max(votes, key=key)


def resolveReviews(movies: list[dict], reviews: list[dict], mergedInto: dict) -> tuple[list[dict], dict]:
    """Reasigna, descarta y oculta. Devuelve (reseñas, cambios por _id). No modifica la entrada."""
    activeMovies = {m["_id"]: m for m in movies if not m["deleted"]}
    changesById: dict = defaultdict(list)
    result = []

    for raw in reviews:
        review = copy.copy(raw)
        changes = changesById[review["_id"]]
        review["deleted"], review["deletedReason"], review["commentHidden"] = False, None, False

        # G2: las reseñas de una copia descartada pasan a la ganadora.
        if review.get("movie_id") in mergedInto:
            setPath(review, "movie_id", mergedInto[review["movie_id"]], "G2", changes)

        if isAnonymous(review):
            _softDelete(review, ANONYMOUS, "B4", changes)
        elif review.get("movie_id") not in activeMovies:
            _softDelete(review, ORPHAN, "B11", changes)

        # B7, B8: el comentario se oculta, el voto sigue contando.
        if not isUsefulComment(review.get("comment")):
            setPath(review, "commentHidden", True, "B7", changes)

        result.append(review)

    # B13: entre las activas, un solo voto por usuario y película. Incluye los pares que
    # aparecen recién al reasignar (un usuario que votó dos copias de la misma película).
    votesByKey = defaultdict(list)
    for review in result:
        if not review["deleted"]:
            votesByKey[(review["user_id"], review["movie_id"])].append(review)
    for (_, movieId), votes in votesByKey.items():
        if len(votes) < 2:
            continue
        winner = pickWinnerVote(votes, activeMovies[movieId].get("released"))
        for review in votes:
            if review is not winner:
                _softDelete(review, DUPLICATE_VOTE, "B13", changesById[review["_id"]])

    # B12: sin rating válido y sin comentario útil no queda nada. Hoy son 0 casos.
    for review in result:
        if not review["deleted"] and review.get("rating") is None and review["commentHidden"]:
            _softDelete(review, NO_CONTENT, "B12", changesById[review["_id"]])

    return result, {k: v for k, v in changesById.items() if v}


def countVisibleComments(movies: list[dict], reviews: list[dict]) -> tuple[list[dict], dict]:
    """num_mflix_comments = reseñas activas con el comentario visible (A16).

    Va al final, cuando ya se sabe qué reseñas quedan. Las películas descartadas quedan en 0.
    """
    visible = Counter(r["movie_id"] for r in reviews if not r["deleted"] and not r["commentHidden"])
    changesById: dict = {}
    result = []
    for raw in movies:
        movie = copy.copy(raw)
        changes: list[Change] = []
        setPath(movie, "num_mflix_comments", visible.get(movie["_id"], 0), "A16", changes)
        if changes:
            changesById[movie["_id"]] = changes
        result.append(movie)
    return result, changesById
