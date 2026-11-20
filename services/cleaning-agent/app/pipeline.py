"""Limpieza completa en el orden de ANOMALIAS (sección 2), sin tocar la base.

Quien la llama lee las colecciones, ejecuta `clean` y escribe el resultado y la auditoría.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from app.duplicates import dedupeMovies
from app.movies import cleanMovie
from app.reviews import cleanReview
from app.votes import countVisibleComments, resolveReviews


@dataclass
class CleaningResult:
    movies: list[dict]
    reviews: list[dict]
    # _id → cambios en el orden en que se aplicaron.
    movieChanges: dict = field(default_factory=dict)
    reviewChanges: dict = field(default_factory=dict)


def _collect(target: defaultdict, changesById: dict) -> None:
    for docId, changes in changesById.items():
        target[docId] += changes


def clean(movies: list[dict], reviews: list[dict], datasetCreated: datetime) -> CleaningResult:
    movieChanges: defaultdict = defaultdict(list)
    reviewChanges: defaultdict = defaultdict(list)

    # 1. Reglas de campo.
    cleanMovies = []
    for raw in movies:
        doc, changes = cleanMovie(raw)
        cleanMovies.append(doc)
        movieChanges[doc["_id"]] += changes
    cleanReviews = []
    for raw in reviews:
        doc, changes = cleanReview(raw, datasetCreated)
        cleanReviews.append(doc)
        reviewChanges[doc["_id"]] += changes

    # 2. Duplicados de películas.
    cleanMovies, changes, mergedInto = dedupeMovies(cleanMovies)
    _collect(movieChanges, changes)

    # 3 a 5. Reasignar, votos duplicados, soft delete y comentarios ocultos.
    cleanReviews, changes = resolveReviews(cleanMovies, cleanReviews, mergedInto)
    _collect(reviewChanges, changes)

    # 6. Contador de reseñas visibles.
    cleanMovies, changes = countVisibleComments(cleanMovies, cleanReviews)
    _collect(movieChanges, changes)

    return CleaningResult(
        cleanMovies,
        cleanReviews,
        {k: v for k, v in movieChanges.items() if v},
        {k: v for k, v in reviewChanges.items() if v},
    )
