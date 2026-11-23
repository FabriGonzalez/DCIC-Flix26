"""Guardar votos contra Mongo real: reemplazo, reentregas, votos viejos y contador."""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pymongo")
from bson import ObjectId  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

from dcicflix_common.interactions import Interaction, InvalidInteraction  # noqa: E402
from ingest import store  # noqa: E402

pytestmark = pytest.mark.mongo

MOVIE, OTHER, DUPLICATE = ObjectId(), ObjectId(), ObjectId()
NOON = datetime.fromisoformat("2026-11-23T12:00:00.123Z")
NOON_IN_MONGO = NOON.replace(tzinfo=None)  # pymongo devuelve UTC sin zona


def vote(**changes) -> Interaction:
    fields = {"user_id": "usr_0001", "movie_id": str(MOVIE), "rating": 5, "comment": "Muy buena", "voted_at": NOON}
    return Interaction(**(fields | changes))


def old_review(**changes) -> dict:
    """Una reseña del dataset, ya limpia."""
    return {
        "movie_id": MOVIE,
        "user_id": "usr_0001",
        "user_name": "Lucas Thomas",
        "user_email": "lucas@example.com",
        "rating": 2,
        "comment": "A long enough comment.",
        "date": datetime(2020, 1, 1),
        "datePrecision": "year",
        "deleted": False,
        "deletedReason": None,
        "commentHidden": False,
    } | changes


def count_of(db, movie_id=MOVIE) -> int:
    return db.movies.find_one({"_id": movie_id})["num_mflix_comments"]


def snapshot(db) -> tuple:
    return list(db.reviews.find().sort("_id")), list(db.movies.find().sort("_id"))


@pytest.fixture
def base(db):
    db.movies.insert_many(
        [
            {"_id": MOVIE, "deleted": False, "num_mflix_comments": 0},
            {"_id": OTHER, "deleted": False, "num_mflix_comments": 0},
            {"_id": DUPLICATE, "deleted": True, "mergedInto": MOVIE, "num_mflix_comments": 0},
        ]
    )
    store.ensure_indexes(db)
    return db


# --- Voto nuevo ---------------------------------------------------------------


def test_voto_nuevo(base):
    assert store.save(base, vote()) is True
    review = base.reviews.find_one()
    del review["_id"]
    assert review == {
        "user_id": "usr_0001",
        "movie_id": MOVIE,
        "rating": 5,
        "comment": "Muy buena",
        "date": NOON_IN_MONGO,
        "datePrecision": "day",
        "deleted": False,
        "deletedReason": None,
        "commentHidden": False,
    }
    assert count_of(base) == 1


def test_votos_de_distintos_usuarios_y_peliculas(base):
    for changes in ({}, {"user_id": "usr_0002"}, {"movie_id": str(OTHER)}):
        store.save(base, vote(**changes))
    assert base.reviews.count_documents({}) == 3
    assert (count_of(base), count_of(base, OTHER)) == (2, 1)


@pytest.mark.parametrize("comment", ["", "  \n "])
def test_sin_texto_cuenta_el_voto_y_no_la_resenia(base, comment):
    store.save(base, vote(comment=comment))
    review = base.reviews.find_one()
    assert (review["rating"], review["commentHidden"]) == (5, True)
    assert count_of(base) == 0


# --- Reemplazo ----------------------------------------------------------------


def test_reemplaza_el_voto_del_dataset(base):
    old_id = base.reviews.insert_one(old_review()).inserted_id
    assert store.save(base, vote()) is True
    (review,) = base.reviews.find()
    assert review["_id"] == old_id
    assert (review["rating"], review["comment"]) == (5, "Muy buena")
    assert (review["date"], review["datePrecision"]) == (NOON_IN_MONGO, "day")
    assert count_of(base) == 1


def test_reemplaza_un_voto_sin_fecha(base):
    base.reviews.insert_one(old_review(date=None, datePrecision=None))
    assert store.save(base, vote()) is True
    assert base.reviews.find_one()["rating"] == 5


def test_borrar_el_texto_resta_del_contador(base):
    store.save(base, vote())
    store.save(base, vote(comment="", voted_at=NOON + timedelta(minutes=1)))
    assert count_of(base) == 0
    store.save(base, vote(voted_at=NOON + timedelta(minutes=2)))
    assert count_of(base) == 1


def test_no_toca_los_votos_descartados(base):
    discarded = old_review(deleted=True, deletedReason="duplicateVote")
    # Dos descartados iguales conviven: el índice único solo mira los activos.
    base.reviews.insert_many([dict(discarded), dict(discarded)])
    store.save(base, vote())
    assert base.reviews.count_documents({"deleted": True, "rating": 2, "deletedReason": "duplicateVote"}) == 2
    assert base.reviews.count_documents({"deleted": False, "rating": 5}) == 1
    assert count_of(base) == 1


# --- Reentregas y orden -------------------------------------------------------


def test_la_reentrega_no_cambia_nada(base):
    store.save(base, vote())
    before = snapshot(base)
    assert store.save(base, vote()) is True
    assert snapshot(base) == before


def test_un_voto_viejo_no_pisa_a_uno_nuevo(base):
    store.save(base, vote(rating=1, voted_at=NOON))
    before = snapshot(base)
    assert store.save(base, vote(rating=5, voted_at=NOON - timedelta(milliseconds=1))) is False
    assert snapshot(base) == before


def test_la_reentrega_completa_un_contador_que_quedo_sin_actualizar(base):
    # Caída entre guardar la reseña y actualizar el contador.
    store.save(base, vote())
    base.movies.update_one({"_id": MOVIE}, {"$set": {"num_mflix_comments": 0}})
    store.save(base, vote())
    assert count_of(base) == 1


def test_un_voto_viejo_tambien_corrige_el_contador(base):
    store.save(base, vote())
    base.movies.update_one({"_id": MOVIE}, {"$set": {"num_mflix_comments": 0}})
    store.save(base, vote(voted_at=NOON - timedelta(days=1)))
    assert count_of(base) == 1


# --- Película inválida e índice -----------------------------------------------


@pytest.mark.parametrize("movie_id", [ObjectId(), DUPLICATE], ids=["inexistente", "descartada"])
def test_rechaza_peliculas_no_activas(base, movie_id):
    with pytest.raises(InvalidInteraction, match="^movie_id:"):
        store.save(base, vote(movie_id=str(movie_id)))
    assert base.reviews.count_documents({}) == 0


def test_crear_el_indice_es_idempotente(base):
    store.ensure_indexes(base)
    store.ensure_indexes(base)


def test_la_base_impide_dos_votos_activos(base):
    store.save(base, vote())
    with pytest.raises(DuplicateKeyError):
        base.reviews.insert_one(old_review())


def test_el_indice_se_puede_crear_antes_de_la_limpieza(db):
    # Los documentos crudos no tienen `deleted`, y hay votos repetidos.
    raw = {"user_id": "usr_0001", "movie_id": MOVIE, "rating": "5"}
    db.reviews.insert_many([dict(raw), dict(raw)])
    store.ensure_indexes(db)
