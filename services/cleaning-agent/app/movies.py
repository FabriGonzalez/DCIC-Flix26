"""Reglas de campo de `movies`: paso 1 de ANOMALIAS (sección 2).

Cada regla mira un solo documento. Lo que necesita comparar copias (completar un `year`
desde otra copia, fusionar duplicados) va en las reglas entre documentos.
"""

import copy
import re
from datetime import datetime

from app.changes import MISSING, Change, getPath, setPath

# --- P1 · year ---------------------------------------------------------------

_FOUR_DIGITS = re.compile(r"\d{4}")


def parseYear(value):
    """'1981è' → 1981, 'circa 1934' → 1934, '2006è2007' → 2006 (A9), -1984 → 1984."""
    if isinstance(value, int) and not isinstance(value, bool):
        return abs(value)
    if isinstance(value, str):
        found = _FOUR_DIGITS.search(value)
        return int(found.group()) if found else None
    return None


# --- P2 · runtime ------------------------------------------------------------

_HOURS_MINUTES = re.compile(r"\s*(\d+)h\s*(\d+)m\s*")
_MINUTES = re.compile(r"\s*(\d+)(\s*min)?\s*")


def parseRuntime(value):
    """Minutos enteros: '1h 25m' → 85, '100 min' → 100, '122' → 122, -90 → 90 (A11)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return abs(value)
    if isinstance(value, str):
        if found := _HOURS_MINUTES.fullmatch(value):
            return int(found.group(1)) * 60 + int(found.group(2))
        if found := _MINUTES.fullmatch(value):
            return int(found.group(1))
    return None


# --- P3 · genres -------------------------------------------------------------

_GENRE_SEPARATOR = re.compile(r"\s*(?:/|\||,)\s*")


def parseGenres(value):
    """'Drama / Romance' → ['Drama', 'Romance']; [' Drama '] → ['Drama']."""
    if isinstance(value, str):
        value = _GENRE_SEPARATOR.split(value)
    if isinstance(value, list):
        return [genre.strip() for genre in value if isinstance(genre, str) and genre.strip()]
    return value


# --- A12, A15, P5 · imdb.rating y A14 · imdb.votes ---------------------------

# 14.5 no es un ×10: las copias sanas de esas películas dicen 7.4, 6.1, 5.2 y 6.4 (A12).
_RATING_SENTINELS = (14.5, -1)
_VOTES_NUMBER = re.compile(r"\d{1,3}(,\d{3})+|\d+")  # '798', '1,208', '1,109,724'


def parseVotes(value):
    """'1,208' → 1208; '' u otra cosa → None, nunca 0 (A14)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and _VOTES_NUMBER.fullmatch(value):
        return int(value.replace(",", ""))
    return None


def _isSentinel(value) -> bool:
    if isinstance(value, str):
        return value.strip() == ""
    return value in _RATING_SENTINELS


def _ratingToNumber(value):
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _fromTimesTen(value):
    # Los ×10 están entre 40 y 84 (P5). 14.5 nunca llega acá: A12 lo anula antes.
    if value is not None and 10 < value <= 100:
        return round(value / 10, 1)
    return value


# --- A17, A18 · listas de personas ------------------------------------------


def rejoinWriters(writers: list[str]) -> list[str]:
    """Une los pedazos de un paréntesis cortado por comas (A17).

    'Claude Miller (scenario' + ' adaptation and dialogue)' → un solo elemento. Pega con ','
    sin espacio: el pedazo ya trae el suyo, y así un número como '20,000' queda intacto.
    """
    result, pending = [], None
    for piece in writers:
        pending = piece if pending is None else pending + "," + piece
        if pending.count("(") <= pending.count(")"):
            result.append(pending)
            pending = None
    if pending is not None:  # nunca cerró: se deja como está
        result.append(pending)
    return result


def dropExactDuplicates(items: list) -> list:
    """Quita los elementos idénticos, rol incluido, y conserva el orden (A18)."""
    return list(dict.fromkeys(items))


# --- A20 · rated, A21 · lastupdated, A23 · poster ---------------------------


def normalizeRated(value: str) -> str:
    upper = value.upper()
    return "NOT RATED" if upper == "UNRATED" else upper


def parseLastUpdated(value):
    """'2015-08-30 23:27:11.263000000' → datetime. fromisoformat acepta los 2 formatos (A21)."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


_OLD_POSTER_HOST = "http://ia.media-imdb.com/"
_POSTER_HOST = "https://m.media-amazon.com/"


def fixPosterHost(url: str) -> str:
    """El servidor viejo responde 403; el nuevo sirve la misma ruta (A23)."""
    if url.startswith(_OLD_POSTER_HOST):
        return _POSTER_HOST + url[len(_OLD_POSTER_HOST) :]
    return url


# --- A25 · awards ------------------------------------------------------------

# La frase tiene hasta 3 partes, todas opcionales.
_AWARDS_PATTERN = re.compile(
    r"""
    ^(?:
        (?P<verb>Won|Nominated\ for)\ (?P<big>\d+)\ [^.]+\.   # "Won 1 Oscar." / "Nominated for 2 Oscars."
        (?:\ Another\ )?
    )?
    (?:(?P<wins>\d+)\ wins?)?                                  # "11 wins" / "1 win"
    (?:\ &\ )?
    (?:(?P<noms>\d+)\ nominations?)?                           # "15 nominations" / "1 nomination"
    \.?$
    """,
    re.VERBOSE,
)


def parseAwards(text: str):
    """(wins, nominations) leídos de awards.text, o None si la frase no se entiende.

    'Nominated for 2 Oscars. Another 11 wins & 15 nominations.' → (11, 17).
    """
    found = _AWARDS_PATTERN.match(text.strip())
    if not found or not any(found.groups()):
        return None
    verb, big = found["verb"], int(found["big"] or 0)
    wins, noms = int(found["wins"] or 0), int(found["noms"] or 0)
    return wins + (big if verb == "Won" else 0), noms + (big if verb == "Nominated for" else 0)


# --- Documento completo ------------------------------------------------------


def cleanMovie(raw: dict) -> tuple[dict, list[Change]]:
    """Aplica las reglas de campo en el orden de ANOMALIAS. No modifica `raw`."""
    doc = copy.deepcopy(raw)
    changes: list[Change] = []

    def apply(path: str, rule: str, fix) -> None:
        value = getPath(doc, path)
        if value is not MISSING:
            setPath(doc, path, fix(value), rule, changes)

    apply("year", "P1", parseYear)
    apply("runtime", "P2", parseRuntime)
    # El contrato es "int o null": el campo faltante pasa a null. No es una corrección
    # de un valor, así que no va a la auditoría.
    doc.setdefault("runtime", None)
    apply("genres", "P3", parseGenres)
    apply("title", "P4", lambda t: t.strip() if isinstance(t, str) else t)

    # A14 antes que A15: primero se sabe qué votos quedan en null.
    apply("imdb.votes", "A14", parseVotes)
    apply("imdb.rating", "A12", lambda r: None if _isSentinel(r) else r)
    apply("imdb.rating", "P5", _ratingToNumber)
    apply("imdb.rating", "P5", _fromTimesTen)
    if getPath(doc, "imdb.votes") is None:
        apply("imdb.rating", "A15", lambda r: None)

    # A17 antes que A18: primero se unen los pedazos y después se buscan repetidos.
    apply("writers", "A17", lambda w: rejoinWriters(w) if isinstance(w, list) else w)
    for field in ("writers", "cast", "directors"):
        apply(field, "A18", lambda v: dropExactDuplicates(v) if isinstance(v, list) else v)

    apply("rated", "A20", lambda r: normalizeRated(r) if isinstance(r, str) else r)
    # A21 no va a la auditoría: el texto viene en todas las películas, así que convertirlo
    # es preparar el formato, no corregir una anomalía. El original queda en moviesRaw.
    if "lastupdated" in doc:
        doc["lastupdated"] = parseLastUpdated(doc["lastupdated"])
    apply("poster", "A23", lambda p: fixPosterHost(p) if isinstance(p, str) else p)
    _recalculateAwards(doc, changes)

    return doc, changes


def _recalculateAwards(doc: dict, changes: list[Change]) -> None:
    text = getPath(doc, "awards.text")
    if not isinstance(text, str):
        return
    parsed = parseAwards(text)
    if parsed is None:
        # Los números quedan como están; la auditoría registra que no se pudo leer.
        changes.append(Change("awards", "A25", text, None, note="frase de premios no reconocida"))
        return
    setPath(doc, "awards.wins", parsed[0], "A25", changes)
    setPath(doc, "awards.nominations", parsed[1], "A25", changes)
