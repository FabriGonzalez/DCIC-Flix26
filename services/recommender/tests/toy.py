"""Catálogo de juguete para los tests: 8 películas con señales conocidas.

    0, 1, 2  atracos: plots parecidos, Crime; 0 y 1 del mismo director, 0 y 2 con De Niro
    3, 4     romance: plots parecidos, Romance; comparten a Kate
    5        ciencia ficción, sin nadie compartido
    6        sin plot ni géneros: solo personas (comparte a Solo con 5)
    7        drama, entre romance y ciencia ficción
"""

import numpy as np

from app.index import build_catalog

MOVIES = [
    {"_id": "m0", "genres": ["Crime", "Thriller"], "directors": ["Michael Mann"], "cast": ["Robert De Niro"],
     "imdb": {"rating": 8.3, "votes": 500_000}},
    {"_id": "m1", "genres": ["Crime", "Thriller"], "directors": ["Michael Mann"], "cast": ["Al Pacino"],
     "imdb": {"rating": 7.5, "votes": 200_000}},
    {"_id": "m2", "genres": ["Crime"], "cast": ["Robert De Niro"], "writers": ["Someone (novel)"],
     "imdb": {"rating": 6.0, "votes": 3_000}},
    {"_id": "m3", "genres": ["Romance"], "cast": ["Kate"], "imdb": {"rating": 7.8, "votes": 900_000}},
    {"_id": "m4", "genres": ["Drama", "Romance"], "cast": ["Kate"], "imdb": {"rating": 6.5, "votes": 40}},
    {"_id": "m5", "genres": ["Sci-Fi"], "cast": ["Solo"], "imdb": {"rating": 9.0, "votes": 40}},
    {"_id": "m6", "cast": ["Solo"], "imdb": None},
    {"_id": "m7", "genres": ["Drama"], "cast": ["Nobody Else"], "writers": ["Someone"],
     "imdb": {"rating": 5.0, "votes": 10_000}},
]

PLOTS = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.9, 0.1, 0.0],
        [0.8, 0.2, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.9, 0.1],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 0.0],  # sin plot
        [0.1, 0.5, 0.5],
    ],
    dtype=np.float32,
)


def catalog():
    return build_catalog(MOVIES, PLOTS)
