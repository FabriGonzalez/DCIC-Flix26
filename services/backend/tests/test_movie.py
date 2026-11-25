import asyncio

import pytest
from bson import ObjectId

from app import catalog, movie

ID = ObjectId()

CLEAN = {
    "_id": ID,
    "title": "The Godfather",
    "year": 1972,
    "poster": "https://m.media-amazon.com/images/M/x.jpg",
    "genres": ["Crime", "Drama"],
    "imdb": {"rating": 9.2, "votes": 1_000_000},
    "plot": "Corta.",
    "fullplot": "Larga.",
    "runtime": 175,
    "rated": "R",
    "directors": ["Francis Ford Coppola"],
    "cast": ["Marlon Brando", "Al Pacino"],
    "countries": ["USA"],
    "languages": ["English", "Italian"],
    "awards": {"wins": 3, "nominations": 2, "text": "Won 3 Oscars."},
    "deleted": False,
}


def detail(**changes) -> dict:
    return movie.to_detail({**CLEAN, **changes})


# --- Conversión -------------------------------------------------------------------------


def test_clean_movie_passes_as_is():
    assert movie.to_detail(CLEAN) == {
        **catalog.to_card(CLEAN),
        "plot": "Larga.",
        "runtime": 175,
        "rated": "R",
        "directors": ["Francis Ford Coppola"],
        "cast": ["Marlon Brando", "Al Pacino"],
        "countries": ["USA"],
        "languages": ["English", "Italian"],
        "imdbVotes": 1_000_000,
        "awards": "Won 3 Oscars.",
    }


def test_missing_fields_are_null_or_empty():
    result = movie.to_detail({"_id": ID})
    assert result["plot"] is None
    assert result["runtime"] is None
    assert result["rated"] is None
    assert result["directors"] == result["cast"] == result["countries"] == result["languages"] == []
    assert result["imdbVotes"] is None
    assert result["awards"] is None


def test_short_plot_when_full_is_missing_or_blank():
    assert detail(fullplot=None)["plot"] == "Corta."
    assert detail(fullplot="   ")["plot"] == "Corta."


@pytest.mark.parametrize("runtime", ["1h 30min", "90", 0, -5, True])  # formas del crudo (P2)
def test_runtime_outside_contract_is_null(runtime):
    assert detail(runtime=runtime)["runtime"] is None


def test_rated_not_uppercase_is_null():
    assert detail(rated="Unrated")["rated"] is None  # A20: la limpieza lo pasa a NOT RATED


@pytest.mark.parametrize("votes", ["1,208", 0, None])  # texto y centinela (A14)
def test_votes_outside_contract_are_null(votes):
    assert detail(imdb={"rating": 7.0, "votes": votes})["imdbVotes"] is None


# --- Contra Mongo -----------------------------------------------------------------------


def run_get(mongo_uri: str, movie_id: str) -> dict | None:
    from pymongo import AsyncMongoClient

    async def go():
        client = AsyncMongoClient(mongo_uri)
        try:
            return await movie.get_movie(client, movie_id)
        finally:
            await client.close()

    return asyncio.run(go())


def insert(mongo_uri: str, documents: list[dict]) -> None:
    import pymongo

    with pymongo.MongoClient(mongo_uri) as client:
        client.get_default_database()[catalog.COLLECTION].insert_many(documents)


@pytest.mark.mongo
def test_finds_active_and_raw_movies(mongo_uri):
    active, raw = ObjectId(), ObjectId()
    insert(mongo_uri, [
        {"_id": active, "title": "Activa", "deleted": False},
        {"_id": raw, "title": "Cruda"},  # durante la limpieza: sin el campo
    ])
    assert run_get(mongo_uri, str(active))["title"] == "Activa"
    assert run_get(mongo_uri, str(raw))["title"] == "Cruda"


@pytest.mark.mongo
def test_merged_copy_returns_the_winner_with_its_id(mongo_uri):
    winner, copy = ObjectId(), ObjectId()
    insert(mongo_uri, [
        {"_id": winner, "title": "Ganadora", "deleted": False},
        {"_id": copy, "title": "Copia", "deleted": True, "deletedReason": "duplicateMovie", "mergedInto": winner},
    ])
    result = run_get(mongo_uri, str(copy))
    assert result["id"] == str(winner)
    assert result["title"] == "Ganadora"


@pytest.mark.mongo
def test_deleted_without_merge_target_is_not_found(mongo_uri):
    gone = ObjectId()
    insert(mongo_uri, [{"_id": gone, "title": "Borrada", "deleted": True, "mergedInto": None}])
    assert run_get(mongo_uri, str(gone)) is None


@pytest.mark.mongo
@pytest.mark.parametrize("movie_id", ["no-es-un-id", str(ObjectId())])
def test_invalid_or_unknown_id_is_not_found(mongo_uri, movie_id):
    assert run_get(mongo_uri, movie_id) is None
