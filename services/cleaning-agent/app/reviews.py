"""Reglas de campo de `reviews`: paso 1 de ANOMALIAS (sección 2).

Corrige `rating` y `date`. Detectar reseñas anónimas (B4) y comentarios basura (B7, B8)
también se hace mirando una sola reseña, pero actuar sobre eso (soft delete, ocultar el
comentario) es el paso 5, así que acá solo se exponen las funciones que lo detectan.
"""

import copy
import re
from datetime import UTC, datetime

from app.changes import MISSING, Change, getPath, setPath

PRECISION_DAY = "day"
PRECISION_YEAR = "year"

# --- B5, B6, B14 · rating ----------------------------------------------------

_VALID_RATINGS = range(1, 6)
_STARS = re.compile(r"(\d+)[- ]stars?", re.IGNORECASE)


def parseRating(value):
    """Entero de 1 a 5, o None. '4' → 4 (B14); 10, 0, -1 o null → None (B5)."""
    if isinstance(value, str) and value.strip() in {"1", "2", "3", "4", "5"}:
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value in _VALID_RATINGS:
        return value
    return None


def starsInText(comment):
    """Rating escrito en el comentario ('4 stars', '3-star'), si está entre 1 y 5 (B6)."""
    found = _STARS.search(comment) if isinstance(comment, str) else None
    if found and int(found.group(1)) in _VALID_RATINGS:
        return int(found.group(1))
    return None


# --- B2, B9, B10 · date ------------------------------------------------------

_DAY_MONTH_YEAR = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_CIRCA = re.compile(r"circa (\d{4})")


def parseDate(value):
    """(fecha, precisión) o (None, None) si no se sabe.

    Date se deja; entero = epoch en ms; 'dd/mm/yyyy' (B2); 'yyyy-mm-dd';
    'circa 2023' → 1/1/2023 con precisión de año (B9); 'yesterday' → None (B9).
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None), PRECISION_DAY
    if isinstance(value, int) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=UTC).replace(tzinfo=None), PRECISION_DAY
    if isinstance(value, str):
        if found := _DAY_MONTH_YEAR.fullmatch(value):
            return datetime(int(found[3]), int(found[2]), int(found[1])), PRECISION_DAY
        if found := _ISO_DATE.fullmatch(value):
            return datetime(int(found[1]), int(found[2]), int(found[3])), PRECISION_DAY
        if found := _CIRCA.fullmatch(value):
            return datetime(int(found[1]), 1, 1), PRECISION_YEAR
    return None, None


# --- B4 · anónimas, B7, B8 · comentarios -------------------------------------

_ANONYMOUS_IDS = {"", "usr_0000"}
UPDATE_PREFIX = "Update: Changed my mind after rewatching."
_LOW_CONTENT = {"nice", "good", "ok"}
# Hay un hueco en la distribución entre 3 y 8 palabras (B7).
_MIN_USEFUL_WORDS = 3


def isAnonymous(review: dict) -> bool:
    """Sin user_id o con usr_0000: no hay forma de saber quién votó (B4)."""
    userId = review.get("user_id")
    return not isinstance(userId, str) or userId.strip() in _ANONYMOUS_IDS


def isUsefulComment(comment) -> bool:
    """False para basura ('', '...', 'asdf') y sin contenido ('nice', 'good', 'ok').

    Se evalúa sin el prefijo de Update, que no dice nada sobre la película.
    """
    if not isinstance(comment, str):
        return False
    body = comment.strip()
    if body.startswith(UPDATE_PREFIX):
        body = body[len(UPDATE_PREFIX) :].strip()
    return len(body.split()) >= _MIN_USEFUL_WORDS and body.lower() not in _LOW_CONTENT


# --- Documento completo ------------------------------------------------------


def cleanReview(raw: dict, datasetCreated: datetime) -> tuple[dict, list[Change]]:
    """Corrige rating y date. No modifica `raw`.

    datasetCreated: fecha de creación del dataset; una reseña posterior es imposible (B10).
    Si el rating queda en None, lo infiere el LLM en otro paso.
    """
    doc = copy.deepcopy(raw)
    changes: list[Change] = []

    rating = getPath(doc, "rating")
    rating = None if rating is MISSING else rating
    parsedRating = parseRating(rating)
    setPath(doc, "rating", parsedRating, "B14" if isinstance(rating, str) and parsedRating else "B5", changes)
    if parsedRating is None and (stars := starsInText(doc.get("comment"))) is not None:
        setPath(doc, "rating", stars, "B6", changes)

    date = getPath(doc, "date")
    parsedDate, precision = parseDate(None if date is MISSING else date)
    if parsedDate is not None and parsedDate > datasetCreated:
        parsedDate, precision, rule = None, None, "B10"
    elif parsedDate is None or precision == PRECISION_YEAR:
        rule = "B9"
    else:
        rule = "B2"
    setPath(doc, "date", parsedDate, rule, changes)
    # Campo nuevo, no una corrección: no va a la auditoría. Sin fecha no hay precisión:
    # date y datePrecision son null juntos o ninguno lo es.
    doc["datePrecision"] = precision

    return doc, changes
