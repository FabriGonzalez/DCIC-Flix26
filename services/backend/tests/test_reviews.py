import asyncio
from datetime import datetime

import pytest
from bson import ObjectId

from app import reviews

ID = ObjectId()
MOVIE = ObjectId()

CLEAN = {
    "_id": ID,
    "movie_id": MOVIE,
    "user_id": "usr_0937",
    "user_name": "Leo Roberts",
    "user_email": "leo.roberts551@proton.me",
    "rating": 4,
    "comment": "A very compelling watch.",
    "date": datetime(2024, 3, 10, 0, 1, 43),  # así la devuelve pymongo: UTC sin zona
    "datePrecision": "day",
    "commentHidden": False,
    "deleted": False,
}


def review(**changes) -> dict:
    return reviews.to_review({**CLEAN, **changes})


# --- Conversión -------------------------------------------------------------------------


def test_clean_review_passes_without_email():
    assert reviews.to_review(CLEAN) == {
        "id": str(ID),
        "userName": "Leo Roberts",
        "rating": 4,
        "comment": "A very compelling watch.",
        "date": "2024-03-10T00:01:43+00:00",
        "datePrecision": "day",
    }


@pytest.mark.parametrize("rating", ["4", 10, 999, 0, -1, 6, None, True])  # B5, B14 y sin LLM
def test_rating_outside_contract_is_null(rating):
    assert review(rating=rating)["rating"] is None


def test_hidden_comment_keeps_the_rest():
    result = review(commentHidden=True)
    assert result["comment"] is None
    assert result["rating"] == 4
    assert result["userName"] == "Leo Roberts"


def test_null_rating_keeps_the_comment():
    assert review(rating=None)["comment"] == "A very compelling watch."


@pytest.mark.parametrize("date", ["yesterday", "circa 2023", "10/03/2024", 1710028903000, None])  # B2, B9
def test_date_not_a_date_is_null_and_so_is_precision(date):
    result = review(date=date)
    assert result["date"] is None
    assert result["datePrecision"] is None


def test_year_precision_passes():
    assert review(date=datetime(2023, 1, 1), datePrecision="year")["datePrecision"] == "year"


def test_raw_date_without_precision_is_day():
    raw = {**CLEAN}
    del raw["datePrecision"], raw["commentHidden"], raw["deleted"]
    assert reviews.to_review(raw)["datePrecision"] == "day"


def test_blank_name_and_comment_are_null():
    result = review(user_name="  ", comment="  ")
    assert result["userName"] is None
    assert result["comment"] is None


# --- Contra Mongo -----------------------------------------------------------------------


def run_list(mongo_uri: str, movie_id: str) -> dict | None:
    from pymongo import AsyncMongoClient

    async def go():
        client = AsyncMongoClient(mongo_uri)
        try:
            return await reviews.list_reviews(client, movie_id)
        finally:
            await client.close()

    return asyncio.run(go())


def insert(mongo_uri: str, documents: list[dict]) -> None:
    import pymongo

    with pymongo.MongoClient(mongo_uri) as client:
        client.get_default_database()[reviews.COLLECTION].insert_many(documents)


def make(comment: str, date, movie_id=MOVIE, **extra) -> dict:
    return {"_id": ObjectId(), "movie_id": movie_id, "user_email": "x@y.z", "comment": comment, "date": date, **extra}


@pytest.mark.mongo
def test_only_active_reviews_of_the_movie(mongo_uri):
    insert(mongo_uri, [
        make("Activa", datetime(2024, 1, 1), deleted=False),
        make("Cruda", datetime(2024, 1, 2)),  # durante la limpieza: sin el campo
        make("Borrada", datetime(2024, 1, 3), deleted=True),
        make("De otra", datetime(2024, 1, 4), movie_id=ObjectId()),
    ])
    result = run_list(mongo_uri, str(MOVIE))
    assert [r["comment"] for r in result["items"]] == ["Cruda", "Activa"]
    assert result["total"] == 2


@pytest.mark.mongo
def test_newest_first_and_dates_as_text_last(mongo_uri):
    insert(mongo_uri, [
        make("Texto", "yesterday"),
        make("Vieja", datetime(2020, 1, 1)),
        make("Nueva", datetime(2024, 1, 1)),
        make("Sin fecha", None),
    ])
    comments = [r["comment"] for r in run_list(mongo_uri, str(MOVIE))["items"]]
    assert comments[:2] == ["Nueva", "Vieja"]
    assert set(comments[2:]) == {"Texto", "Sin fecha"}


@pytest.mark.mongo
def test_email_never_leaves_mongo(mongo_uri):
    insert(mongo_uri, [make("Con mail", datetime(2024, 1, 1))])
    assert "x@y.z" not in str(run_list(mongo_uri, str(MOVIE)))


@pytest.mark.mongo
def test_limit_keeps_total(mongo_uri):
    insert(mongo_uri, [make(f"Reseña {i}", datetime(2024, 1, 1)) for i in range(reviews.LIMIT + 3)])
    result = run_list(mongo_uri, str(MOVIE))
    assert len(result["items"]) == reviews.LIMIT
    assert result["total"] == reviews.LIMIT + 3


@pytest.mark.mongo
def test_invalid_id_is_none(mongo_uri):
    assert run_list(mongo_uri, "no-es-un-id") is None
