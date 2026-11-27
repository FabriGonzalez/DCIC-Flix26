"""Votar por la API, de punta a punta: frontend → backend → cola → ingest-consumer → Mongo → ficha."""

import json
import time

import pytest

import compose
import votes

pytestmark = pytest.mark.dynamic

TIMEOUT = 20


@pytest.fixture(scope="module", autouse=True)
def system():
    if not compose.containers():
        pytest.skip("no hay nada levantado: correr `docker compose up -d --wait`")
    if '"ready"' not in compose.get_from_frontend("/api/status")[2]:
        pytest.skip("el sistema no está ready: todavía no se puede votar")


@pytest.fixture
def voter():
    voter = votes.Voter()
    voter.register()
    yield voter
    voter.clean()


def wait_until_saved(voter: votes.Voter, rating: int) -> None:
    deadline = time.monotonic() + TIMEOUT
    while voter.saved() != [rating] or not votes.is_drained():
        if time.monotonic() > deadline:
            pytest.fail(f"a los {TIMEOUT} s: guardados {voter.saved()}, cola {votes.queue()}")
        time.sleep(0.5)


def own_reviews(voter: votes.Voter) -> list[dict]:
    """Las reseñas del votante en la ficha, por id: los nombres se repiten."""
    body = compose.get_from_frontend(f"/api/movies/{voter.movie_id}/reviews")[2]
    return [r for r in json.loads(body)["items"] if r["userId"] == voter.user_id]


def test_un_voto_llega_a_la_ficha_con_el_nombre(voter):
    assert own_reviews(voter) == []
    assert voter.post(4) == 202
    wait_until_saved(voter, 4)
    assert voter.added_to_count() == 1
    [review] = own_reviews(voter)
    assert (review["userName"], review["rating"], review["comment"]) == (voter.NAME, 4, "Muy buena")


def test_cambiar_el_voto_deja_uno_solo(voter):
    for rating in (1, 2, 5):
        assert voter.post(rating) == 202
    wait_until_saved(voter, 5)
    assert voter.added_to_count() == 1
    assert [r["rating"] for r in own_reviews(voter)] == [5]


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"rating": 6}, 422),
        ({"user_id": "usr_0000"}, 422),
        ({"user_id": "usr_9999"}, 404),
        ({"movie_id": "0" * 24}, 404),
        ({"movie_id": "nada"}, 404),
    ],
)
def test_un_voto_rechazado_no_llega_a_la_cola(voter, changes, expected):
    original = voter.user_id, voter.movie_id
    try:
        voter.user_id = changes.get("user_id", voter.user_id)
        voter.movie_id = changes.get("movie_id", voter.movie_id)
        errors = compose.rabbitmqctl("list_queues", "name", "messages")
        assert voter.post(changes.get("rating", 4)) == expected
    finally:
        # clean() borra por estos ids: tienen que ser los del votante.
        voter.user_id, voter.movie_id = original
    assert voter.saved() == []
    assert compose.rabbitmqctl("list_queues", "name", "messages") == errors
