"""Limpieza contra Mongo real: marca, copia cruda, auditoría y repetición tras una caída."""

from datetime import datetime

import pytest

pytest.importorskip("pymongo")
from bson import ObjectId  # noqa: E402

from app import runner, store  # noqa: E402

pytestmark = pytest.mark.mongo

WINNER, LOSER, OTHER = ObjectId(), ObjectId(), ObjectId()
REVIEW_OF_LOSER, TEXT_RATING = ObjectId(), ObjectId()


def _movie(_id, lastupdated, **fields):
    base = {
        "_id": _id,
        "title": "Black Rain",
        "year": 1989,
        "runtime": 125,
        "imdb": {"id": 97, "rating": 6.6, "votes": 100},
        "directors": ["Ridley Scott"],
        "lastupdated": lastupdated,
        "released": datetime(1989, 9, 22),
        "poster": "https://m.media-amazon.com/images/x.jpg",
        "awards": {"wins": 0, "nominations": 2, "text": "Nominated for 2 Oscars."},
        "num_mflix_comments": 0,
    }
    base.update(fields)
    return base


def _review(_id, movieId, **fields):
    base = {
        "_id": _id,
        "movie_id": movieId,
        "user_id": "usr_0001",
        "rating": 4,
        "comment": "A long enough comment about the movie.",
        "date": datetime(2020, 1, 1),
    }
    base.update(fields)
    return base


MOVIES = [
    _movie(WINNER, "2015-09-01 00:00:00.000000000"),
    # Copia duplicada (mismo imdb.id), más vieja: se fusiona en WINNER (A3, G2).
    _movie(LOSER, "2015-08-01 00:00:00.000000000", year="1989"),
    _movie(OTHER, "2015-08-01 00:00:00", title="  Other ", imdb={"id": 98, "rating": 7.0, "votes": 10}, directors=["X"]),
]
REVIEWS = [
    _review(REVIEW_OF_LOSER, LOSER),
    _review(TEXT_RATING, OTHER, user_id="usr_0002", rating="5"),
]


@pytest.fixture
def rawDb(db):
    db.movies.insert_many([dict(m) for m in MOVIES])
    db.reviews.insert_many([dict(r) for r in REVIEWS])
    return db


def _dump(db, name):
    return list(db[name].find().sort("_id"))


def _snapshot(db):
    return {name: _dump(db, name) for name in ("movies", "reviews", "moviesRaw", "reviewsRaw", "audit")}


def test_firstRunCleansCopiesRawAndAudits(rawDb):
    runner.runCleaning(rawDb)

    state = store.readState(rawDb)
    assert (state["status"], state["rawCopied"], state["eventPublished"]) == ("done", True, False)
    assert state["finishedAt"] >= state["startedAt"]

    # La copia cruda es el dataset tal como vino.
    assert _dump(rawDb, "moviesRaw") == sorted(MOVIES, key=lambda d: d["_id"])
    assert _dump(rawDb, "reviewsRaw") == sorted(REVIEWS, key=lambda d: d["_id"])

    movies = {m["_id"]: m for m in rawDb.movies.find()}
    assert (movies[LOSER]["deleted"], movies[LOSER]["mergedInto"]) == (True, WINNER)
    assert movies[OTHER]["title"] == "Other"
    assert isinstance(movies[WINNER]["lastupdated"], datetime)
    assert rawDb.reviews.find_one({"_id": REVIEW_OF_LOSER})["movie_id"] == WINNER
    assert rawDb.reviews.find_one({"_id": TEXT_RATING})["rating"] == 5


def test_auditHasOneRecordPerDocumentWithChangesInOrder(rawDb):
    runner.runCleaning(rawDb)

    audit = {a["_id"]: a for a in rawDb.audit.find()}
    assert audit[LOSER]["collection"] == "movies"
    assert [(c["rule"], c["field"], c["before"], c["after"]) for c in audit[LOSER]["changes"]][:1] == [
        ("P1", "year", "1989", 1989)
    ]
    assert ("G2", "deleted") in [(c["rule"], c["field"]) for c in audit[LOSER]["changes"]]
    assert [(c["rule"], c["before"], c["after"]) for c in audit[REVIEW_OF_LOSER]["changes"]] == [("G2", LOSER, WINNER)]
    assert audit[TEXT_RATING]["collection"] == "reviews"
    # lastupdated es conversión de formato, no anomalía: no va a la auditoría.
    assert not [c for a in audit.values() for c in a["changes"] if c["field"] == "lastupdated"]


def test_doneMarkSkipsCleaning(rawDb):
    runner.runCleaning(rawDb)
    # Un cambio posterior (por ejemplo, un voto nuevo) no se pisa en el próximo arranque.
    rawDb.reviews.update_one({"_id": TEXT_RATING}, {"$set": {"rating": 1}})
    runner.runCleaning(rawDb)
    assert rawDb.reviews.find_one({"_id": TEXT_RATING})["rating"] == 1


def test_crashMidWriteIsRepeatedWithSameResult(rawDb, db, mongoClient, monkeypatch):
    # Resultado de referencia: una corrida sin caídas en otra base.
    reference = mongoClient[db.name + "_ref"]
    reference.movies.insert_many([dict(m) for m in MOVIES])
    reference.reviews.insert_many([dict(r) for r in REVIEWS])
    runner.runCleaning(reference)
    expected = _snapshot(reference)
    mongoClient.drop_database(reference.name)

    # Caída después de escribir las películas limpias y antes de las reseñas.
    realReplace = store.replaceDocuments

    def crashOnReviews(database, name, docs):
        if name == store.REVIEWS:
            raise RuntimeError("caída simulada")
        realReplace(database, name, docs)

    monkeypatch.setattr(store, "replaceDocuments", crashOnReviews)
    with pytest.raises(RuntimeError):
        runner.runCleaning(rawDb)
    assert (store.readState(rawDb)["status"], store.readState(rawDb)["eventPublished"]) == ("running", False)
    assert rawDb.movies.find_one({"_id": LOSER})["deleted"] is True  # a medio limpiar

    monkeypatch.setattr(store, "replaceDocuments", realReplace)
    runner.runCleaning(rawDb)

    # Mismo resultado y sin auditoría duplicada, aunque las películas ya estaban limpias.
    assert _snapshot(rawDb) == expected
    assert store.readState(rawDb)["status"] == "done"


def test_rawIsNotCopiedAgainAfterItIsComplete(rawDb, monkeypatch):
    def crash(*args):
        raise RuntimeError("caída simulada")

    realReplace = store.replaceDocuments
    monkeypatch.setattr(store, "replaceDocuments", crash)
    with pytest.raises(RuntimeError):
        runner.runCleaning(rawDb)
    # movies cambió después de la copia (simula una escritura a medias).
    rawDb.movies.update_one({"_id": OTHER}, {"$set": {"title": "a medio limpiar"}})

    calls = []
    monkeypatch.setattr(store, "replaceDocuments", realReplace)
    monkeypatch.setattr(store, "copyRaw", calls.append)
    runner.runCleaning(rawDb)

    assert calls == []
    assert rawDb.moviesRaw.find_one({"_id": OTHER})["title"] == "  Other "
    assert rawDb.movies.find_one({"_id": OTHER})["title"] == "Other"


def test_eventPendingUntilMarkedPublished(rawDb):
    assert not runner.eventPending(rawDb)  # sin marca
    runner.runCleaning(rawDb)
    assert runner.eventPending(rawDb)
    runner.markEventPublished(rawDb)
    assert not runner.eventPending(rawDb)
