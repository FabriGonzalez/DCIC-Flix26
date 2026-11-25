import asyncio

import pytest
from pymongo.errors import AutoReconnect

from app import users


def review(user_id, name="Casey Adams", email="casey@uns.edu.ar", **extra) -> dict:
    return {"user_id": user_id, "user_name": name, "user_email": email, **extra}


# --- Usuarios nuevos y búsqueda ---------------------------------------------------------


def test_preloaded_users_continue_the_dataset_ids():
    assert [u["_id"] for u in users.PRELOADED] == ["usr_2001", "usr_2002", "usr_2003", "usr_2004", "usr_2005"]
    assert len({u["email"] for u in users.PRELOADED}) == 5
    assert all(u["email"].endswith("@dcicflix.test") and u["preloaded"] for u in users.PRELOADED)


def test_blank_query_has_no_filter():
    assert users.search_filter("   ") == {}


def test_query_is_text_not_regex():
    assert users.search_filter("a.b")["$or"][0]["name"]["$regex"] == r"a\.b"


# --- Carga en segundo plano -------------------------------------------------------------


def run_loader(monkeypatch, outcomes: list) -> tuple[users.UserLoader, list]:
    """Corre el UserLoader con un load() que devuelve o lanza, en orden, `outcomes`."""
    remaining, fatal = iter(outcomes), []

    async def fake_load(mongo):
        outcome = next(remaining)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(users, "load", fake_load)
    monkeypatch.setattr(users, "_RETRY_DELAY", 0)

    async def go():
        loader = users.UserLoader(None, on_fatal=fatal.append)
        assert not loader.loaded
        loader.start()
        await loader._task
        await loader.stop()
        return loader

    return asyncio.run(go()), fatal


def test_loader_retries_until_mongo_answers(monkeypatch):
    loader, fatal = run_loader(monkeypatch, [AutoReconnect("caído"), AutoReconnect("caído"), 2005])
    assert loader.loaded
    assert fatal == []


def test_loader_reports_a_bug_instead_of_retrying(monkeypatch):
    bug = ValueError("bug")
    loader, fatal = run_loader(monkeypatch, [bug])
    assert not loader.loaded
    assert fatal == [bug]


def test_loader_can_stop_while_waiting_to_retry(monkeypatch):
    async def failing_load(mongo):
        raise AutoReconnect("caído")

    monkeypatch.setattr(users, "load", failing_load)
    fatal = []

    async def go():
        loader = users.UserLoader(None, on_fatal=fatal.append)
        loader.start()
        await asyncio.sleep(0.01)
        await asyncio.wait_for(loader.stop(), 1)
        return loader

    assert not asyncio.run(go()).loaded
    assert fatal == []


# --- Contra Mongo -----------------------------------------------------------------------


def with_mongo(mongo_uri: str, work):
    from pymongo import AsyncMongoClient

    async def go():
        client = AsyncMongoClient(mongo_uri)
        try:
            return await work(client)
        finally:
            await client.close()

    return asyncio.run(go())


def load(mongo_uri: str) -> int:
    return with_mongo(mongo_uri, users.load)


def search(mongo_uri: str, query: str = "") -> dict:
    return with_mongo(mongo_uri, lambda client: users.list_users(client, query))


@pytest.fixture
def db(mongo_uri):
    import pymongo

    with pymongo.MongoClient(mongo_uri) as client:
        yield client.get_default_database()


@pytest.mark.mongo
def test_load_takes_one_user_per_id(mongo_uri, db):
    db.reviews.insert_many([review("usr_0001"), review("usr_0001"), review("usr_0002", "Alex Hill", "alex@uns.edu.ar")])
    assert load(mongo_uri) == 2 + 5
    assert db.users.find_one({"_id": "usr_0001"}) == {
        "_id": "usr_0001", "name": "Casey Adams", "email": "casey@uns.edu.ar", "preloaded": False,
    }


@pytest.mark.mongo
def test_load_ignores_anonymous_and_reviews_without_name(mongo_uri, db):
    db.reviews.insert_many([
        review("", "Anonymous", ""),
        review("usr_0000", "Anonymous", ""),
        review(None),
        {"user_id": "test_abc", "rating": 4},  # del ingest-consumer
        {"user_id": "usr_0001", "rating": 4},  # un voto nuevo de uno del dataset
        review("usr_0001"),
    ])
    assert load(mongo_uri) == 1 + 5
    assert db.users.find_one({"_id": "usr_0001"})["name"] == "Casey Adams"


@pytest.mark.mongo
def test_load_gives_the_same_users_before_and_after_cleaning(mongo_uri, db):
    db.reviews.insert_many([review("usr_0001"), review("usr_0002", deleted=True), review("usr_0003", deleted=False)])
    assert load(mongo_uri) == 3 + 5


@pytest.mark.mongo
def test_load_again_changes_nothing(mongo_uri, db):
    db.reviews.insert_one(review("usr_0001"))
    load(mongo_uri)
    before = list(db.users.find().sort("_id"))
    assert load(mongo_uri) == 6
    assert list(db.users.find().sort("_id")) == before


@pytest.mark.mongo
def test_load_keeps_existing_users_and_completes_the_missing_ones(mongo_uri, db):
    # Como si la carga anterior se hubiera cortado, con usuarios ya modificados.
    db.reviews.insert_many([review("usr_0001"), review("usr_0002")])
    db.users.insert_one({"_id": "usr_0001", "name": "Otro", "email": "otro@uns.edu.ar", "preloaded": False})
    db.users.insert_one({"_id": "usr_2001", "name": "Otra", "email": "otra@uns.edu.ar", "preloaded": True})
    assert load(mongo_uri) == 2 + 5
    assert db.users.find_one({"_id": "usr_0001"})["name"] == "Otro"
    assert db.users.find_one({"_id": "usr_2001"})["name"] == "Otra"


@pytest.mark.mongo
def test_load_can_run_twice_at_the_same_time(mongo_uri, db):
    db.reviews.insert_many([review(f"usr_{i:04}") for i in range(1, 501)])

    async def both(client):
        return await asyncio.gather(users.load(client), users.load(client))

    with_mongo(mongo_uri, both)
    assert db.users.count_documents({}) == 505


@pytest.mark.mongo
def test_list_shows_preloaded_first_and_limits(mongo_uri, db):
    db.reviews.insert_many([review(f"usr_{i:04}", f"Aaron {i:04}") for i in range(1, 41)])
    load(mongo_uri)
    result = search(mongo_uri)
    assert result["total"] == 45
    assert len(result["items"]) == users.LIMIT
    assert [u["id"] for u in result["items"][:6]] == [u["_id"] for u in users.PRELOADED] + ["usr_0001"]
    assert [u["preloaded"] for u in result["items"][:6]] == [True] * 5 + [False]


@pytest.mark.mongo
def test_search_by_name_email_or_id_without_returning_the_email(mongo_uri, db):
    db.reviews.insert_many([review("usr_0142", "Casey Adams", "c.a@uns.edu.ar"), review("usr_0143", "Alex Hill", "z@x.com")])
    load(mongo_uri)
    expected = {"items": [{"id": "usr_0142", "name": "Casey Adams", "preloaded": False}], "total": 1}
    for query in ("casey ad", "C.A@UNS", "usr_0142", " 0142 "):
        assert search(mongo_uri, query) == expected, query
    assert search(mongo_uri, "nadie") == {"items": [], "total": 0}
    assert search(mongo_uri, ".*") == {"items": [], "total": 0}
