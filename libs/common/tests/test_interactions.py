"""Formato del mensaje de `interactions`, sin broker ni Mongo."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from dcicflix_common.interactions import MAX_COMMENT_LENGTH, Interaction, InvalidInteraction, decode, encode

VALID = {
    "user_id": "usr_0142",
    "movie_id": "573a1393f29313caabcdd7d8",
    "rating": 5,
    "comment": "Una obra maestra 🎬",
    "votedAt": "2026-11-23T18:04:05.123Z",
}


def body(**changes) -> bytes:
    return json.dumps(VALID | changes).encode()


def test_lee_un_mensaje_valido():
    assert decode(body()) == Interaction(
        user_id="usr_0142",
        movie_id="573a1393f29313caabcdd7d8",
        rating=5,
        comment="Una obra maestra 🎬",
        voted_at=datetime(2026, 11, 23, 18, 4, 5, 123000, tzinfo=UTC),
    )


def test_ida_y_vuelta():
    assert json.loads(encode(decode(body()))) == VALID


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_rating_valido(rating):
    assert decode(body(rating=rating)).rating == rating


def test_comentario_vacio_es_valido():
    assert decode(body(comment="")).comment == ""


def test_comentario_en_el_tope():
    assert len(decode(body(comment="x" * MAX_COMMENT_LENGTH)).comment) == MAX_COMMENT_LENGTH


def test_ignora_campos_desconocidos():
    assert decode(body(otro="x")) == decode(body())


def test_la_fecha_queda_en_utc():
    assert decode(body(votedAt="2026-11-23T15:04:05.123-03:00")) == decode(body())


def test_la_fecha_se_trunca_a_milisegundos():
    # Mongo guarda milisegundos: si no, el mismo voto parecería posterior al guardado.
    assert decode(body(votedAt="2026-11-23T18:04:05.123999Z")) == decode(body())


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": ""},
        {"user_id": "   "},
        {"user_id": " usr_0142"},
        {"user_id": "usr_0000"},
        {"user_id": None},
        {"user_id": 142},
        {"user_id": {"$ne": ""}},
        {"user_id": "usr_\ud83d"},
        {"movie_id": ""},
        {"movie_id": "573a"},
        {"movie_id": "z" * 24},
        {"movie_id": "573a1393f29313caabcdd7d8\n"},
        {"movie_id": None},
        {"rating": 0},
        {"rating": 6},
        {"rating": -1},
        {"rating": "5"},
        {"rating": 4.5},
        {"rating": 5.0},
        {"rating": True},
        {"rating": None},
        {"rating": [5]},
        {"comment": None},
        {"comment": 5},
        {"comment": "medio emoji \ud83d"},
        {"comment": "x" * (MAX_COMMENT_LENGTH + 1)},
        {"votedAt": None},
        {"votedAt": 1795456800},
        {"votedAt": "ayer"},
        {"votedAt": "2026-11-23"},
        {"votedAt": "2026-11-23T18:04:05"},
        {"votedAt": "0001-01-01T00:00:00+23:00"},
    ],
    ids=lambda changes: ascii(changes)[:40],
)
def test_rechaza_campos_invalidos(changes):
    (field,) = changes
    with pytest.raises(InvalidInteraction, match=f"^{field}:"):
        decode(body(**changes))


@pytest.mark.parametrize("field", VALID)
def test_rechaza_campos_faltantes(field):
    data = {k: v for k, v in VALID.items() if k != field}
    with pytest.raises(InvalidInteraction, match=f"faltan campos: {field}"):
        decode(json.dumps(data).encode())


@pytest.mark.parametrize(
    "raw",
    [b"", b"hola", b"{", b"null", b"[]", b'"texto"', b"\xff\xfe\xfd", b"[" * 100_000, b"9" * 10_000],
    ids=["vacio", "texto", "cortado", "null", "lista", "string", "binario", "anidado", "entero-enorme"],
)
def test_rechaza_lo_que_no_es_un_objeto_json(raw):
    with pytest.raises(InvalidInteraction):
        decode(raw)


def test_el_backend_no_puede_construir_uno_invalido():
    with pytest.raises(InvalidInteraction, match="^rating:"):
        Interaction("usr_0142", VALID["movie_id"], 9, "", datetime.now(UTC))


def test_fecha_con_otra_zona_al_construir():
    local = datetime(2026, 11, 23, 15, 4, tzinfo=timezone(timedelta(hours=-3)))
    assert Interaction("usr_0142", VALID["movie_id"], 5, "", local).voted_at.utcoffset() == timedelta(0)
