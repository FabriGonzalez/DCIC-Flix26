import asyncio

import pytest
from bson import ObjectId

from app import catalog

ID = ObjectId()

CLEAN = {
    "_id": ID,
    "title": "The Godfather",
    "year": 1972,
    "poster": "https://m.media-amazon.com/images/M/x.jpg",
    "genres": ["Crime", "Drama"],
    "imdb": {"rating": 9.2, "votes": 1_000_000},
    "deleted": False,
}


def card(**changes) -> dict:
    return catalog.to_card({**CLEAN, **changes})


# --- Conversión: valida contra el contrato, no rescata ---------------------------------


def test_clean_movie_passes_as_is():
    assert catalog.to_card(CLEAN) == {
        "id": str(ID),
        "title": "The Godfather",
        "year": 1972,
        "poster": "https://m.media-amazon.com/images/M/x.jpg",
        "genres": ["Crime", "Drama"],
        "imdbRating": 9.2,
    }


@pytest.mark.parametrize(
    "year",
    ["1989", "circa 1934", -1989, 0, True, None],  # formas del crudo (P1) y un bool
)
def test_year_outside_contract_is_null(year):
    assert card(year=year)["year"] is None


def test_missing_fields_are_null():
    assert catalog.to_card({"_id": ID}) == {
        "id": str(ID), "title": None, "year": None, "poster": None, "genres": [], "imdbRating": None,
    }


def test_genres_as_text_is_empty_not_split():
    assert card(genres="Drama / Thriller")["genres"] == []


def test_genres_keeps_only_strings():
    assert card(genres=["Drama", None, 3])["genres"] == ["Drama"]


@pytest.mark.parametrize("rating", ["7.2", 72, 0, -1, None, True])  # texto, ×10, centinelas (P5, A12)
def test_rating_outside_contract_is_null(rating):
    assert card(imdb={"rating": rating})["imdbRating"] is None


def test_rating_int_within_scale_passes():
    assert card(imdb={"rating": 6})["imdbRating"] == 6


def test_imdb_not_a_dict_is_null():
    assert card(imdb="7.2")["imdbRating"] is None


def test_poster_from_old_host_is_null():
    # A23: la única con el servidor viejo, sin https. La limpieza la cambia.
    assert card(poster="http://ia.media-imdb.com/images/M/x.jpg")["poster"] is None


# --- Búsqueda ---------------------------------------------------------------------------


def test_blank_query_has_no_filter():
    assert catalog.title_filter("   ") == {}


def test_query_is_text_not_regex():
    assert catalog.title_filter("(500) Days")["title"]["$regex"] == r"\(500\)\ Days"


def test_query_non_ascii_becomes_e_grave():
    assert catalog.title_filter("Amélie")["title"]["$regex"] == "Amèlie"


# --- Contra Mongo -----------------------------------------------------------------------


def run_list(mongo_uri: str, query: str = "", page: int = 1) -> dict:
    from pymongo import AsyncMongoClient

    async def go():
        client = AsyncMongoClient(mongo_uri)
        try:
            return await catalog.list_movies(client, query, page)
        finally:
            await client.close()

    return asyncio.run(go())


def insert(mongo_uri: str, documents: list[dict]) -> None:
    import pymongo

    with pymongo.MongoClient(mongo_uri) as client:
        client.get_default_database()[catalog.COLLECTION].insert_many(documents)


def movie(title: str, votes, **extra) -> dict:
    return {"_id": ObjectId(), "title": title, "imdb": {"votes": votes}, **extra}


@pytest.mark.mongo
def test_deleted_movies_are_hidden_but_raw_ones_without_field_are_shown(mongo_uri):
    insert(mongo_uri, [
        movie("Activa", 10, deleted=False),
        movie("Copia", 20, deleted=True),
        movie("Cruda", 30),  # durante la limpieza: todavía sin el campo
    ])
    result = run_list(mongo_uri)
    assert [m["title"] for m in result["items"]] == ["Cruda", "Activa"]
    assert result["total"] == 2


@pytest.mark.mongo
def test_votes_as_text_go_last_not_first(mongo_uri):
    insert(mongo_uri, [
        movie("Texto", "1,208"),
        movie("Pocos", 5),
        movie("Muchos", 900),
        movie("Sin votos", None),
    ])
    titles = [m["title"] for m in run_list(mongo_uri)["items"]]
    assert titles[:2] == ["Muchos", "Pocos"]
    assert set(titles[2:]) == {"Texto", "Sin votos"}


@pytest.mark.mongo
def test_pages_do_not_overlap_even_with_ties(mongo_uri):
    # Todas con los mismos votos: sin el desempate por _id el orden entre páginas no es fijo.
    insert(mongo_uri, [movie(f"Película {i}", 100) for i in range(catalog.PAGE_SIZE + 5)])
    first = run_list(mongo_uri, page=1)
    second = run_list(mongo_uri, page=2)
    ids = [m["id"] for m in first["items"] + second["items"]]
    assert len(first["items"]) == catalog.PAGE_SIZE
    assert len(second["items"]) == 5
    assert len(set(ids)) == catalog.PAGE_SIZE + 5
    assert first["total"] == second["total"] == catalog.PAGE_SIZE + 5


@pytest.mark.mongo
def test_page_past_the_end_is_empty(mongo_uri):
    insert(mongo_uri, [movie("Única", 1)])
    result = run_list(mongo_uri, page=3)
    assert result["items"] == []
    assert result["total"] == 1


@pytest.mark.mongo
def test_search_is_case_insensitive_and_finds_lost_characters(mongo_uri):
    insert(mongo_uri, [
        movie("Amèlie", 10),  # así viene en el dataset (A13)
        movie("The Godfather", 20),
        movie("Godzilla", 30, deleted=True),
    ])
    assert [m["title"] for m in run_list(mongo_uri, "godf")["items"]] == ["The Godfather"]
    assert [m["title"] for m in run_list(mongo_uri, "amélie")["items"]] == ["Amèlie"]
    assert run_list(mongo_uri, "godz")["total"] == 0
