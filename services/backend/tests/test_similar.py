import asyncio

import httpx
import pytest
from bson import ObjectId

from app import catalog, recommender, similar

URL = "http://recommender:8000"


def client_answering(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run_ids(handler, movie_id: str = "abc") -> list[str] | None:
    async def go():
        async with client_answering(handler) as http:
            return await similar.similar_ids(http, URL, movie_id)

    return asyncio.run(go())


# --- Pedido al recommender --------------------------------------------------------------


def test_returns_ids_in_order_and_asks_for_the_limit():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json={"items": [{"movie_id": "b", "score": 0.9}, {"movie_id": "a", "score": 0.5}]})

    assert run_ids(handler, "x") == ["b", "a"]
    assert seen[0].path == "/movies/x/similar"
    assert seen[0].params["limit"] == str(similar.LIMIT)


def test_movie_not_active_in_recommender_is_none():
    assert run_ids(lambda request: httpx.Response(404, json={"detail": "la película no está activa"})) is None


@pytest.mark.parametrize("code", [503, 500])
def test_recommender_error_is_unavailable(code):
    with pytest.raises(recommender.RecommenderUnavailable):
        run_ids(lambda request: httpx.Response(code, json={"detail": "x"}))


def test_recommender_down_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("recommender caído")

    with pytest.raises(recommender.RecommenderUnavailable):
        run_ids(handler)


def test_invalid_id_does_not_call_the_recommender():
    def handler(request):
        raise AssertionError("no debería pedirle nada al recommender")

    async def go():
        async with client_answering(handler) as http:
            # mongo no se usa: el id se descarta antes.
            return await similar.list_similar(http, URL, None, "../health")

    assert asyncio.run(go()) is None


# --- Contra Mongo -----------------------------------------------------------------------


def insert(mongo_uri: str, documents: list[dict]) -> None:
    import pymongo

    with pymongo.MongoClient(mongo_uri) as client:
        client.get_default_database()[catalog.COLLECTION].insert_many(documents)


def run_list(mongo_uri: str, handler, movie_id: str) -> list[dict] | None:
    from pymongo import AsyncMongoClient

    async def go():
        client = AsyncMongoClient(mongo_uri)
        try:
            async with client_answering(handler) as http:
                return await similar.list_similar(http, URL, client, movie_id)
        finally:
            await client.close()

    return asyncio.run(go())


def answering_ids(ids: list[ObjectId]):
    return lambda request: httpx.Response(200, json={"items": [{"movie_id": str(i), "score": 1.0} for i in ids]})


@pytest.mark.mongo
def test_cards_keep_the_recommender_order(mongo_uri):
    first, second, third = ObjectId(), ObjectId(), ObjectId()
    insert(mongo_uri, [
        {"_id": first, "title": "Primera", "deleted": False},
        {"_id": second, "title": "Segunda", "deleted": False},
        {"_id": third, "title": "Tercera", "deleted": False},
    ])
    result = run_list(mongo_uri, answering_ids([third, first, second]), str(ObjectId()))
    assert [card["title"] for card in result] == ["Tercera", "Primera", "Segunda"]
    assert result[0] == catalog.to_card({"_id": third, "title": "Tercera"})


@pytest.mark.mongo
def test_missing_or_deleted_movies_are_skipped(mongo_uri, caplog):
    active, deleted, unknown = ObjectId(), ObjectId(), ObjectId()
    insert(mongo_uri, [
        {"_id": active, "title": "Activa", "deleted": False},
        {"_id": deleted, "title": "Copia", "deleted": True, "mergedInto": active},
    ])
    result = run_list(mongo_uri, answering_ids([deleted, unknown, active]), str(ObjectId()))
    assert [card["title"] for card in result] == ["Activa"]
    assert str(deleted) in caplog.text and str(unknown) in caplog.text


@pytest.mark.mongo
def test_no_similar_is_an_empty_list(mongo_uri):
    assert run_list(mongo_uri, answering_ids([]), str(ObjectId())) == []
