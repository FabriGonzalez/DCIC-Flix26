"""Mensaje de la cola `interactions`: un voto con reseña. Lo publica el backend y lo
guarda el ingest-consumer; con las dos puntas acá, el formato no puede divergir.

    {"user_id": "usr_0142", "movie_id": "573a1393f29313caabcdd7d8",
     "rating": 5, "comment": "Great movie", "votedAt": "2026-11-23T18:04:05.123Z"}

Del usuario viaja solo el id: el nombre y el email los recupera el backend al leer.

Un Interaction siempre es válido: se comprueba al construirlo, así que ni el backend puede
publicar uno inválido ni el consumer recibirlo. Lo que necesita Mongo (que la película
exista) lo comprueba el consumer.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

RATINGS = range(1, 6)
# La reseña más larga del dataset tiene 254. El tope evita un documento que Mongo rechace.
MAX_COMMENT_LENGTH = 5000

# Identificador de los votos anónimos del dataset (ANOMALIAS, B4).
_ANONYMOUS_ID = "usr_0000"
_OBJECT_ID = re.compile(r"[0-9a-f]{24}")
_FIELDS = ("user_id", "movie_id", "rating", "comment", "votedAt")


class InvalidInteraction(ValueError):
    """El mensaje no se puede guardar, y reintentar no lo arregla: va a interactions.errors."""


@dataclass(frozen=True)
class Interaction:
    user_id: str
    movie_id: str  # ObjectId en hexadecimal: JSON no tiene ese tipo
    rating: int
    comment: str  # puede ser ""
    voted_at: datetime  # cuándo votó, no cuándo se guarda. Con zona; queda en UTC

    def __post_init__(self) -> None:
        _check_text("user_id", self.user_id)
        if self.user_id != self.user_id.strip() or self.user_id in ("", _ANONYMOUS_ID):
            raise InvalidInteraction("user_id: vacío, anónimo o con espacios alrededor")

        _check_text("movie_id", self.movie_id)
        if not _OBJECT_ID.fullmatch(self.movie_id):
            raise InvalidInteraction("movie_id: no son 24 dígitos hexadecimales en minúscula")

        # type() y no isinstance: True es un int en Python, y True == 1.
        if type(self.rating) is not int or self.rating not in RATINGS:
            raise InvalidInteraction("rating: no es un entero de 1 a 5")

        _check_text("comment", self.comment)
        if len(self.comment) > MAX_COMMENT_LENGTH:
            raise InvalidInteraction(f"comment: más de {MAX_COMMENT_LENGTH} caracteres")

        object.__setattr__(self, "voted_at", _to_utc_milliseconds(self.voted_at))


def encode(interaction: Interaction) -> bytes:
    return json.dumps(
        {
            "user_id": interaction.user_id,
            "movie_id": interaction.movie_id,
            "rating": interaction.rating,
            "comment": interaction.comment,
            "votedAt": interaction.voted_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
    ).encode()


def decode(body: bytes) -> Interaction:
    """Lee un mensaje. Cualquier problema del contenido es InvalidInteraction.

    Los campos desconocidos se ignoran: el backend puede agregar uno sin romper al consumer.
    """
    try:
        data = json.loads(body)
    # ValueError cubre JSON roto, bytes que no son texto y enteros de miles de dígitos.
    except (ValueError, RecursionError) as exc:
        raise InvalidInteraction(f"no es JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidInteraction("el JSON no es un objeto")
    if missing := [field for field in _FIELDS if field not in data]:
        raise InvalidInteraction(f"faltan campos: {', '.join(missing)}")

    return Interaction(
        user_id=data["user_id"],
        movie_id=data["movie_id"],
        rating=data["rating"],
        comment=data["comment"],
        voted_at=_parse_date(data["votedAt"]),
    )


def _check_text(field: str, value) -> None:
    if not isinstance(value, str):
        raise InvalidInteraction(f"{field}: no es texto")
    try:
        # JSON admite medio emoji ("\ud83d"), pero Mongo solo guarda UTF-8 válido.
        value.encode()
    except UnicodeEncodeError as exc:
        raise InvalidInteraction(f"{field}: no se puede escribir en UTF-8") from exc


def _parse_date(value) -> datetime:
    if not isinstance(value, str):
        raise InvalidInteraction("votedAt: no es texto")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInteraction("votedAt: no es una fecha ISO 8601") from exc


def _to_utc_milliseconds(value: datetime) -> datetime:
    """En UTC y truncada a milisegundos, la precisión de Mongo: si no, al comparar un voto
    con el mismo voto ya guardado parecería más nuevo."""
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidInteraction("votedAt: falta la zona horaria")
    try:
        utc = value.astimezone(UTC)
    except OverflowError as exc:  # año 1 o 9999, corrido por la zona
        raise InvalidInteraction("votedAt: fuera de rango") from exc
    return utc.replace(microsecond=utc.microsecond // 1000 * 1000)
