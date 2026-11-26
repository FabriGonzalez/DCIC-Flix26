import asyncio

import httpx
import pytest
from bson import ObjectId

from app import catalog, rankings, recommender

URL = "http://recommender:8000"


def fake_recommender(genres: list[str], ranking_of: dict[str, list[str]], seen: list | None = None):
    """Un recommender que responde /genres en ese orden y /rankings con esos ids."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url)
        if request.url.path == "/genres":
            return httpx.Response(200, json={"items": [{"genre": g, "movies": 1} for g in genres]})
        genre = request.url.params["genre"]
        items = [{"movie_id": i, "wr": 3.5} for i in ranking_of.get(genre, [])]
        return httpx.Response(200, json={"genre": genre, "items": items})

    return handler


def run_ids(handler) -> list[tuple[str, list[str]]]:
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await rankings.genre_ids(http, URL)

    return asyncio.run(go())


# --- Pedidos al recommender -------------------------------------------------------------


def test_rows_keep_the_genre_order_and_skip_excluded_genres():
    seen = []
    handler = fake_recommender(
        ["Drama", "Comedy", "Short", "Western", "News", "Talk-Show"],
        {"Drama": ["d1", "d2"], "Comedy": ["c1"], "Western": ["w1"]},
        seen,
    )
    assert run_ids(handler) == [("Drama", ["d1", "d2"]), ("Comedy", ["c1"]), ("Western", ["w1"])]
    asked = [url.params["genre"] for url in seen if url.path == "/rankings"]
    assert sorted(asked) == ["Comedy", "Drama", "Western"]  # a los excluidos ni se les pide
    assert all(url.params["limit"] == str(rankings.PER_ROW) for url in seen if url.path == "/rankings")


@pytest.mark.parametrize("failing", ["/genres", "/rankings"])
def test_any_recommender_error_is_unavailable(failing):
    good = fake_recommender(["Drama"], {"Drama": ["d1"]})

    def handler(request):
        if request.url.path == failing:
            return httpx.Response(503, json={"detail": "sin índice"})
        return good(request)

    with pytest.raises(recommender.RecommenderUnavailable):
        run_ids(handler)


def test_recommender_down_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("recommender caído")

    with pytest.raises(recommender.RecommenderUnavailable):
        run_ids(handler)


# --- Contra Mongo -----------------------------------------------------------------------


def insert(mongo_uri: str, documents: list[dict]) -> None:
    import pymongo

    with pymongo.MongoClient(mongo_uri) as client:
        client.get_default_database()[catalog.COLLECTION].insert_many(documents)


def run_rows(mongo_uri: str, handler) -> list[dict]:
    from pymongo import AsyncMongoClient

    async def go():
        client = AsyncMongoClient(mongo_uri)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                return await rankings.list_rows(http, URL, client)
        finally:
            await client.close()

    return asyncio.run(go())


@pytest.mark.mongo
def test_rows_with_cards_in_order_sharing_movies(mongo_uri):
    godfather, airplane, heat = ObjectId(), ObjectId(), ObjectId()
    insert(mongo_uri, [
        {"_id": godfather, "title": "The Godfather", "deleted": False},
        {"_id": airplane, "title": "Airplane!", "deleted": False},
        {"_id": heat, "title": "Heat", "deleted": False},
    ])
    handler = fake_recommender(
        ["Drama", "Comedy", "Crime"],
        {"Drama": [str(heat), str(godfather)], "Comedy": [str(airplane)], "Crime": [str(godfather), str(heat)]},
    )
    rows = run_rows(mongo_uri, handler)
    assert [(row["genre"], [card["title"] for card in row["items"]]) for row in rows] == [
        ("Drama", ["Heat", "The Godfather"]),
        ("Comedy", ["Airplane!"]),
        ("Crime", ["The Godfather", "Heat"]),  # la misma película en dos filas
    ]
    assert rows[1]["items"][0] == catalog.to_card({"_id": airplane, "title": "Airplane!"})


@pytest.mark.mongo
def test_missing_movies_are_skipped_and_empty_rows_dropped(mongo_uri, caplog):
    active, deleted = ObjectId(), ObjectId()
    insert(mongo_uri, [
        {"_id": active, "title": "Activa", "deleted": False},
        {"_id": deleted, "title": "Copia", "deleted": True, "mergedInto": active},
    ])
    handler = fake_recommender(
        ["Drama", "Horror"],
        {"Drama": [str(deleted), str(active)], "Horror": [str(deleted)]},
    )
    rows = run_rows(mongo_uri, handler)
    assert [(row["genre"], [card["title"] for card in row["items"]]) for row in rows] == [("Drama", ["Activa"])]
    assert str(deleted) in caplog.text
