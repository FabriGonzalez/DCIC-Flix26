"""Índice: señales, calibración, vecinos y WR (docs/recomendador.md 9.2)."""

import math

import numpy as np
import pytest

from app import params
from app.index import NEUTRAL_VOTE, build_catalog, build_quality, calibrate, people_matrix, strip_role

import toy


def test_strip_role():
    assert strip_role("Stephen King (novel)") == "Stephen King"
    assert strip_role("Stephen King") == "Stephen King"
    assert strip_role("A (b) c (d)") == "A"


def test_people_drops_names_of_a_single_movie_and_weights_by_rarity():
    T = people_matrix([{"A", "B"}, {"A"}, {"B", "C"}, {"B"}]).toarray()
    # A en 2 películas, B en 3, C en 1: C no tiene columna; columnas ordenadas: A, B
    assert T.shape == (4, 2)
    a, b = math.log(4 / 2), math.log(4 / 3)
    assert T[0] == pytest.approx(np.array([a, b]) / math.hypot(a, b))
    assert T[1] == pytest.approx([1, 0])
    assert T[2] == pytest.approx([0, 1])  # C se descartó: solo queda B


def test_role_is_stripped_before_matching():
    catalog = toy.catalog()
    m2, m7 = catalog.rows["m2"], catalog.rows["m7"]
    # 'Someone (novel)' y 'Someone' son la misma persona
    assert (catalog.T[m2] @ catalog.T[m7].T).toarray()[0, 0] > 0


def test_values_outside_the_contract_are_counted_and_ignored():
    movies = [
        {"_id": "a", "genres": "Drama / Comedy", "cast": "Solo", "imdb": {"rating": "7.5", "votes": 100}},
        {"_id": "b", "genres": ["Drama"], "imdb": {"rating": 7.0, "votes": None}},  # sin IMDb: no es anomalía
        {"_id": "c"},  # todo falta: listas vacías
    ]
    catalog = build_catalog(movies, np.eye(3, dtype=np.float32))
    assert catalog.anomalies == {
        "genres no es una lista de textos": 1,
        "cast no es una lista": 1,
        "imdb.rating o imdb.votes fuera de contrato": 1,
    }
    assert catalog.genres == ["Drama"]
    assert np.isnan(catalog.prior_q).all()


def test_signals_are_unit_rows_or_zero():
    catalog = toy.catalog()
    for X in (catalog.plot, catalog.G, catalog.T.toarray()):
        norms = np.linalg.norm(X, axis=1)
        assert np.all(np.isclose(norms, 1) | np.isclose(norms, 0))
    m6 = catalog.rows["m6"]
    assert not catalog.plot[m6].any() and not catalog.G[m6].any()


def test_calibrate_takes_the_kth_neighbor_without_itself():
    a, b, c = [1.0, 0.0], [0.8, 0.6], [0.0, 1.0]  # a·b = 0,8 · a·c = 0 · b·c = 0,6
    X = np.array([a, b, c])
    # 1.º vecino: a → 0,8, b → 0,8, c → 0,6: mediana 0,8
    assert calibrate(X, rank=1) == pytest.approx(0.8)
    # 2.º vecino: a → 0, b → 0,6, c → 0; solo cuenta el positivo
    assert calibrate(X, rank=2) == pytest.approx(0.6)


def test_calibrate_without_positive_neighbors_is_neutral():
    assert calibrate(np.eye(4)) == 1.0


def test_neighbors_exclude_itself_are_sorted_and_follow_the_formula():
    catalog = toy.catalog()
    n = len(catalog)
    assert catalog.neighbors.shape == (n, n - 1)  # K = min(100, N − 1)
    for row in range(n):
        assert row not in catalog.neighbors[row]
        assert np.all(np.diff(catalog.neighbor_scores[row]) <= 1e-6)

    q_plot, q_genres, q_people = catalog.scales
    i, j = catalog.rows["m0"], catalog.rows["m1"]
    expected = (
        params.W_PLOT * float(catalog.plot[i] @ catalog.plot[j]) / q_plot
        + params.W_GENRES * float(catalog.G[i] @ catalog.G[j]) / q_genres
        + params.W_PEOPLE * min((catalog.T[i] @ catalog.T[j].T).toarray()[0, 0] / q_people, params.PEOPLE_CAP)
    )
    position = list(catalog.neighbors[i]).index(j)
    assert catalog.neighbor_scores[i, position] == pytest.approx(expected, rel=1e-5)
    assert catalog.similarity(np.array([i, j]))[0, 1] == pytest.approx(expected, rel=1e-5)


def test_heist_movies_are_each_others_closest():
    catalog = toy.catalog()
    m0, m1, m2 = (catalog.rows[m] for m in ("m0", "m1", "m2"))
    assert set(catalog.neighbors[m0][:2]) == {m1, m2}


def _votes(catalog, per_movie: dict[str, list[int]]):
    counts, sums = np.zeros(len(catalog)), np.zeros(len(catalog))
    for movie_id, stars in per_movie.items():
        counts[catalog.rows[movie_id]] = len(stars)
        sums[catalog.rows[movie_id]] = sum(stars)
    return counts, sums


VOTES = {"m0": [5, 5, 4], "m1": [4, 3], "m3": [5], "m5": [1, 2], "m6": [4, 4], "m7": [2, 3, 3]}


def test_q5_fit_is_the_regression_of_each_vote_on_q():
    catalog = toy.catalog()
    quality = build_quality(catalog, *_votes(catalog, VOTES))
    xs = [catalog.prior_q[catalog.rows[m]] for m, stars in VOTES.items() for _ in stars if m != "m6"]
    ys = [s for m, stars in VOTES.items() for s in stars if m != "m6"]  # m6 no tiene IMDb
    a, b = np.polyfit(xs, ys, 1)
    assert quality.q5 == pytest.approx((a, b))


def test_wr_starts_from_imdb_and_own_votes_correct_it():
    catalog = toy.catalog()
    quality = build_quality(catalog, *_votes(catalog, VOTES))
    a, b = quality.q5
    all_stars = [s for stars in VOTES.values() for s in stars]
    assert quality.mean_vote == pytest.approx(sum(all_stars) / len(all_stars))

    m0 = catalog.rows["m0"]
    prior = a * catalog.prior_q[m0] + b
    assert quality.wr[m0] == pytest.approx((14 + params.M_OWN * prior) / (3 + params.M_OWN))
    # Sin IMDb, el punto de partida es C
    m6 = catalog.rows["m6"]
    assert quality.wr[m6] == pytest.approx((8 + params.M_OWN * quality.mean_vote) / (2 + params.M_OWN))
    # Sin votos propios, WR es lo que dice IMDb
    m2 = catalog.rows["m2"]
    assert quality.wr[m2] == pytest.approx(a * catalog.prior_q[m2] + b)
    assert quality.wr_z.mean() == pytest.approx(0, abs=1e-9)
    assert quality.wr_z.std() == pytest.approx(1)


def test_imdb_prior_distrusts_few_votes():
    catalog = toy.catalog()
    # m5: un 9 con 40 votos queda casi en el promedio de IMDb del catálogo
    mean_rating = np.mean([m["imdb"]["rating"] for m in toy.MOVIES if m["imdb"]])
    assert catalog.prior_q[catalog.rows["m5"]] == pytest.approx(mean_rating, abs=0.05)
    assert np.isnan(catalog.prior_q[catalog.rows["m6"]])


def test_quality_without_votes():
    catalog = toy.catalog()
    quality = build_quality(catalog, np.zeros(len(catalog)), np.zeros(len(catalog)))
    assert quality.mean_vote == NEUTRAL_VOTE
    assert quality.q5 is None  # no hay votos para ajustar Q₅
    assert np.allclose(quality.wr, NEUTRAL_VOTE)


def test_rankings_are_sorted_by_wr_and_filtered_by_genre():
    catalog = toy.catalog()
    quality = build_quality(catalog, *_votes(catalog, VOTES))
    assert np.all(np.diff(quality.wr[quality.ranking]) <= 0)
    assert sorted(quality.by_genre) == ["Crime", "Drama", "Romance", "Sci-Fi", "Thriller"]
    crime = [catalog.ids[r] for r in quality.by_genre["Crime"]]
    assert sorted(crime) == ["m0", "m1", "m2"]
    assert np.all(np.diff(quality.wr[quality.by_genre["Crime"]]) <= 0)
    assert catalog.genre_counts() == {"Crime": 3, "Drama": 2, "Romance": 2, "Sci-Fi": 1, "Thriller": 2}
