"""Recomendaciones por petición (docs/recomendador.md 9.3)."""

import numpy as np
import pytest

from app import params
from app.index import build_quality
from app.recommend import CONTENT, RANKING, for_user, midpoint, mmr, ranking, similar

import toy

VOTES = {"m0": [5, 5, 4], "m1": [4, 3], "m3": [5], "m5": [1, 2], "m6": [4, 4], "m7": [2, 3, 3]}


@pytest.fixture(scope="module")
def setup():
    catalog = toy.catalog()
    counts, sums = np.zeros(len(catalog)), np.zeros(len(catalog))
    for movie_id, stars in VOTES.items():
        counts[catalog.rows[movie_id]] = len(stars)
        sums[catalog.rows[movie_id]] = sum(stars)
    return catalog, build_quality(catalog, counts, sums)


def ids(catalog, items):
    return [catalog.ids[item.row] for item in items]


def test_without_votes_returns_the_ranking(setup):
    catalog, quality = setup
    source, items = for_user(catalog, quality, [], limit=3)
    assert source == RANKING
    assert [item.row for item in items] == quality.ranking[:3].tolist()
    assert [item.score for item in items] == pytest.approx(quality.wr[quality.ranking[:3]])


def test_midpoint_pulls_a_new_user_towards_c(setup):
    _, quality = setup
    c = quality.mean_vote
    assert midpoint([(0, 5)], quality) == pytest.approx((5 + params.K_USER * c) / (1 + params.K_USER))


def test_a_liked_movie_recommends_its_neighbors(setup):
    catalog, quality = setup
    m0 = catalog.rows["m0"]
    source, items = for_user(catalog, quality, [(m0, 5)], limit=2)
    assert source == CONTENT
    assert set(ids(catalog, items)) == {"m1", "m2"}  # los otros atracos
    assert all(item.because == m0 for item in items)


def test_voted_movies_are_never_recommended(setup):
    catalog, quality = setup
    votes = [(catalog.rows["m0"], 5), (catalog.rows["m1"], 4)]
    _, items = for_user(catalog, quality, votes, limit=len(catalog))
    assert not {"m0", "m1"} & set(ids(catalog, items))


def test_because_is_the_vote_that_contributed_most(setup):
    catalog, quality = setup
    m0, m3 = catalog.rows["m0"], catalog.rows["m3"]
    _, items = for_user(catalog, quality, [(m0, 5), (m3, 5)], limit=4)
    because = {catalog.ids[item.row]: catalog.ids[item.because] for item in items if item.because is not None}
    assert because.get("m1") == "m0"
    assert because.get("m4") == "m3"


def test_only_negative_votes_fall_back_to_the_ranking_without_their_neighbors(setup):
    catalog, quality = setup
    m0 = catalog.rows["m0"]
    # Un voto de 1: el punto medio queda arriba, así que el peso es negativo
    source, items = for_user(catalog, quality, [(m0, 1)], limit=len(catalog))
    assert source == RANKING
    excluded = {m0, *catalog.neighbors[m0].tolist()}
    assert not excluded & {item.row for item in items}


def test_few_candidates_are_completed_with_the_ranking(setup):
    catalog, quality = setup
    m0 = catalog.rows["m0"]
    source, items = for_user(catalog, quality, [(m0, 5)], limit=len(catalog))
    rows = [item.row for item in items]
    assert source == CONTENT
    assert len(rows) == len(set(rows)) == len(catalog) - 1  # todo menos lo votado
    filled = [item for item in items if item.because is None]
    for item in filled:
        assert item.score == pytest.approx(params.BETA * quality.wr_z[item.row])


def test_mmr_trades_score_for_variety():
    scores = np.array([1.0, 0.99, 0.5])
    sim = np.array([[1.0, 0.99, 0.0], [0.99, 1.0, 0.0], [0.0, 0.0, 1.0]])  # 0 y 1 casi iguales
    assert mmr(scores, sim, limit=3, lam=1.0) == [0, 1, 2]  # sin MMR: por puntaje
    assert mmr(scores, sim, limit=3, lam=0.5) == [0, 2, 1]  # la distinta sube
    assert mmr(scores, sim, limit=2) == [0, 1]  # λ = 0,8: la diferencia es chica, no alcanza
    assert mmr(np.array([]), np.zeros((0, 0)), limit=3) == []


def test_similar_returns_neighbors_without_itself(setup):
    catalog, quality = setup
    m3 = catalog.rows["m3"]
    items = similar(catalog, quality, m3, limit=3)
    assert len(items) == 3
    assert m3 not in {item.row for item in items}
    assert ids(catalog, items)[0] == "m4"  # el otro romance, con Kate


def test_ranking_by_genre_and_exclusions(setup):
    catalog, quality = setup
    m0 = catalog.rows["m0"]
    items = ranking(quality, limit=5, excluded={m0}, genre="Crime")
    assert sorted(ids(catalog, items)) == ["m1", "m2"]
