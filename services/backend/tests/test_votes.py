import asyncio
import time
from datetime import UTC, datetime

import pytest
from bson import ObjectId
from pymongo.errors import ServerSelectionTimeoutError

from app import publisher, votes
from dcicflix_common import cleaning

MOVIE = "573a1399f29313caabceeb20"
USER = "usr_2001"
BODY = {"userId": USER, "rating": 5, "comment": "Muy buena"}


# --- Formato ----------------------------------------------------------------------------


def rejection(movie_id, body) -> votes.Rejected:
    with pytest.raises(votes.Rejected) as caught:
        votes.build(movie_id, body)
    return caught.value


def test_valid_body_with_the_backend_time():
    before = datetime.now(UTC)
    vote = votes.build(MOVIE, {**BODY, "votedAt": "2099-01-01T00:00:00Z"})  # la del navegador se ignora
    assert (vote.user_id, vote.movie_id, vote.rating, vote.comment) == (USER, MOVIE, 5, "Muy buena")
    assert abs((vote.voted_at - before).total_seconds()) < 1


def test_comment_is_optional():
    assert votes.build(MOVIE, {"userId": USER, "rating": 1}).comment == ""


def test_movie_id_in_uppercase_is_the_same_movie():
    assert votes.build(MOVIE.upper(), BODY).movie_id == MOVIE


@pytest.mark.parametrize("movie_id", ["nada", "573a", ""])
def test_invalid_movie_id_does_not_exist(movie_id):
    assert rejection(movie_id, BODY).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "texto",
        {},
        {**BODY, "userId": None},
        {**BODY, "userId": ""},
        {**BODY, "userId": "usr_0000"},  # el anónimo
        {**BODY, "userId": {"$ne": None}},  # no llega a Mongo como operador
        {**BODY, "rating": 0},
        {**BODY, "rating": 6},
        {**BODY, "rating": "5"},
        {**BODY, "rating": 4.5},
        {**BODY, "rating": True},
        {**BODY, "comment": None},
        {**BODY, "comment": "x" * 5001},
        {**BODY, "comment": "\ud83d"},  # medio emoji: Mongo no lo guarda
    ],
)
def test_invalid_body(body):
    assert rejection(MOVIE, body).status_code == 422


# --- Contra Mongo -----------------------------------------------------------------------


@pytest.fixture
def db(mongo_uri):
    """Un sistema limpio, con un usuario y una película."""
    import pymongo

    with pymongo.MongoClient(mongo_uri) as client:
        db = client.get_default_database()
        db[cleaning.COLLECTION].insert_one({"_id": cleaning.DOCUMENT_ID, cleaning.STATUS_FIELD: cleaning.DONE})
        db.users.insert_one({"_id": USER, "name": "Ana Torres"})
        db.movies.insert_one({"_id": ObjectId(MOVIE), "deleted": False})
        yield db


def submit(mongo_uri, *, movie_id=MOVIE, user_id=USER, recommender_ready=True, users_loaded=True, error=None) -> list:
    """Los votos publicados."""
    from pymongo import AsyncMongoClient

    published = []

    async def publish(vote):
        if error is not None:
            raise error
        published.append(vote)

    async def go():
        client = AsyncMongoClient(mongo_uri, serverSelectionTimeoutMS=300)
        try:
            vote = votes.build(movie_id, {**BODY, "userId": user_id})
            await votes.submit(
                client, vote, recommender_ready=recommender_ready, users_loaded=users_loaded, publish=publish
            )
        finally:
            await client.close()

    asyncio.run(go())
    return published


def rejected_with(mongo_uri, **options) -> int:
    with pytest.raises(votes.Rejected) as caught:
        submit(mongo_uri, **options)
    return caught.value.status_code


@pytest.mark.mongo
def test_accepted_vote_is_published_once(mongo_uri, db):
    [vote] = submit(mongo_uri)
    assert votes.to_response(vote) == {
        "movieId": MOVIE, "userId": USER, "rating": 5, "comment": "Muy buena", "votedAt": vote.voted_at.isoformat(),
    }
    assert db.reviews.count_documents({}) == 0  # guardar es del ingest-consumer


@pytest.mark.mongo
@pytest.mark.parametrize("mark", [cleaning.PENDING, cleaning.RUNNING])
def test_not_ready_while_cleaning(mongo_uri, db, mark):
    db[cleaning.COLLECTION].update_one({}, {"$set": {cleaning.STATUS_FIELD: mark}})
    assert rejected_with(mongo_uri) == 409


@pytest.mark.mongo
def test_not_ready_without_mark(mongo_uri, db):
    db[cleaning.COLLECTION].delete_many({})
    assert rejected_with(mongo_uri) == 409


@pytest.mark.mongo
def test_not_ready_while_indexing(mongo_uri, db):
    assert rejected_with(mongo_uri, recommender_ready=False) == 409


@pytest.mark.mongo
def test_unknown_user(mongo_uri, db):
    assert rejected_with(mongo_uri, user_id="usr_9999") == 404


@pytest.mark.mongo
def test_missing_user_while_loading_is_not_unknown(mongo_uri, db):
    assert rejected_with(mongo_uri, user_id="usr_0001", users_loaded=False) == 503


@pytest.mark.mongo
def test_existing_user_can_vote_while_loading(mongo_uri, db):
    assert len(submit(mongo_uri, users_loaded=False)) == 1


@pytest.mark.mongo
def test_unknown_movie(mongo_uri, db):
    assert rejected_with(mongo_uri, movie_id=str(ObjectId())) == 404


@pytest.mark.mongo
def test_merged_copy_is_not_active(mongo_uri, db):
    copy = ObjectId()
    db.movies.insert_one({"_id": copy, "deleted": True, "mergedInto": ObjectId(MOVIE)})
    assert rejected_with(mongo_uri, movie_id=str(copy)) == 404


@pytest.mark.mongo
def test_not_published(mongo_uri, db):
    assert rejected_with(mongo_uri, error=publisher.VoteNotPublished("sin conexión")) == 503


def test_mongo_down_is_not_a_rejection():
    started = time.monotonic()
    with pytest.raises(ServerSelectionTimeoutError):  # el endpoint responde 503
        submit("mongodb://127.0.0.1:1/nada")
    assert time.monotonic() - started < 5
