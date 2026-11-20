"""Reglas de campo de movies, con los casos reales que se vieron en el notebook."""

from datetime import datetime

import pytest

from app.movies import (
    cleanMovie,
    dropExactDuplicates,
    fixPosterHost,
    normalizeRated,
    parseAwards,
    parseGenres,
    parseLastUpdated,
    parseRuntime,
    parseVotes,
    parseYear,
    rejoinWriters,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1981, 1981), (-1984, 1984), ("1981è", 1981), ("circa 1934", 1934), ("1989", 1989), ("2006è2007", 2006), (None, None)],
)
def test_parseYear(raw, expected):
    assert parseYear(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(85, 85), (-90, 90), ("1h 25m", 85), ("100 min", 100), ("122", 122), (None, None), ("long", None)],
)
def test_parseRuntime(raw, expected):
    assert parseRuntime(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Drama / Romance", ["Drama", "Romance"]),
        ("Drama|History", ["Drama", "History"]),
        ("Horror, Romance", ["Horror", "Romance"]),
        ([" Drama ", "Sci-Fi"], ["Drama", "Sci-Fi"]),
    ],
)
def test_parseGenres(raw, expected):
    assert parseGenres(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [(798, 798), ("1,208", 1208), ("1,109,724", 1109724), ("", None)])
def test_parseVotes(raw, expected):
    assert parseVotes(raw) == expected


def _movie(**fields):
    base = {
        "title": "X",
        "imdb": {"rating": 7.0, "votes": 100},
        "lastupdated": "2015-08-30 23:27:11.263000000",
        "poster": "https://m.media-amazon.com/images/x.jpg",
        "awards": {"wins": 0, "nominations": 0, "text": "1 win."},
    }
    base.update(fields)
    return base


@pytest.mark.parametrize(
    ("rating", "votes", "expected"),
    [
        (14.5, 100, None),  # A12: centinela, no es un ×10
        (-1, 100, None),  # A12
        ("", 100, None),  # A12
        (64, 100, 6.4),  # P5: escala ×10
        ("7.2", 100, 7.2),  # P5: texto
        (8.1, "", None),  # A15: sin votos no hay rating
    ],
)
def test_imdbRating(rating, votes, expected):
    doc, _ = cleanMovie(_movie(imdb={"rating": rating, "votes": votes}))
    assert doc["imdb"]["rating"] == expected


def test_imdbRatingIntBecomesFloatWithoutChange():
    doc, changes = cleanMovie(_movie(imdb={"rating": 7, "votes": 100}))
    assert isinstance(doc["imdb"]["rating"], float)
    assert not [c for c in changes if c.field == "imdb.rating"]


def test_rejoinWriters():
    pieces = ["Claude Miller (scenario", " adaptation and dialogue)", "Luc Béraud"]
    assert rejoinWriters(pieces) == ["Claude Miller (scenario, adaptation and dialogue)", "Luc Béraud"]


def test_rejoinWritersKeepsNumbersWithCommas():
    assert rejoinWriters(["Jules Verne (novel 20", "000 Leagues)"]) == ["Jules Verne (novel 20,000 Leagues)"]


def test_dropExactDuplicatesKeepsRoles():
    names = ["Jonathan Baker", "Amy Albany (memoir)", "Jonathan Baker", "Amy Albany"]
    assert dropExactDuplicates(names) == ["Jonathan Baker", "Amy Albany (memoir)", "Amy Albany"]


def test_writersRejoinedBeforeDeduplicating():
    doc, changes = cleanMovie(_movie(writers=["A (story", " idea)", "A (story, idea)"]))
    assert doc["writers"] == ["A (story, idea)"]
    assert [c.rule for c in changes if c.field == "writers"] == ["A17", "A18"]


@pytest.mark.parametrize(("raw", "expected"), [("Approved", "APPROVED"), ("UNRATED", "NOT RATED"), ("Unrated", "NOT RATED"), ("GP", "GP")])
def test_normalizeRated(raw, expected):
    assert normalizeRated(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2015-08-30 23:27:11.263000000", datetime(2015, 8, 30, 23, 27, 11, 263000)),
        ("2015-08-30 23:27:11", datetime(2015, 8, 30, 23, 27, 11)),
    ],
)
def test_parseLastUpdated(raw, expected):
    assert parseLastUpdated(raw) == expected


def test_fixPosterHost():
    assert fixPosterHost("http://ia.media-imdb.com/images/M/a.jpg") == "https://m.media-amazon.com/images/M/a.jpg"
    assert fixPosterHost("https://m.media-amazon.com/images/M/a.jpg") == "https://m.media-amazon.com/images/M/a.jpg"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nominated for 2 Oscars. Another 11 wins & 15 nominations.", (11, 17)),  # Blade Runner
        ("Won 1 Oscar. Another 5 wins & 3 nominations.", (6, 3)),
        ("3 wins & 2 nominations.", (3, 2)),
        ("1 nomination.", (0, 1)),
        ("algo ilegible", None),
    ],
)
def test_parseAwards(text, expected):
    assert parseAwards(text) == expected


def test_unreadableAwardsKeepNumbersAndLeaveNote():
    doc, changes = cleanMovie(_movie(awards={"wins": 4, "nominations": 2, "text": "algo ilegible"}))
    assert (doc["awards"]["wins"], doc["awards"]["nominations"]) == (4, 2)
    assert [c.note for c in changes if c.rule == "A25"] == ["frase de premios no reconocida"]


def test_cleanMovieRecordsOriginalValuesAndDoesNotMutateInput():
    raw = _movie(title="  Sikumi ", runtime="1h 25m")
    doc, changes = cleanMovie(raw)
    assert raw["title"] == "  Sikumi " and raw["runtime"] == "1h 25m"
    byField = {c.field: c for c in changes}
    assert (byField["title"].rule, byField["title"].before, byField["title"].after) == ("P4", "  Sikumi ", "Sikumi")
    assert (byField["runtime"].before, byField["runtime"].after) == ("1h 25m", 85)


def test_missingListsStayMissing():
    doc, changes = cleanMovie(_movie())
    assert "genres" not in doc and "writers" not in doc
    assert not [c for c in changes if c.field in ("genres", "writers")]


def test_missingRuntimeBecomesNullWithoutChange():
    doc, changes = cleanMovie(_movie())
    assert doc["runtime"] is None
    assert not [c for c in changes if c.field == "runtime"]
