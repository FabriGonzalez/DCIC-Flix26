"""Películas duplicadas: agrupación (A3, A4), fusión (A5, A6) y soft delete (G2)."""

from datetime import datetime

from app.duplicates import dedupeMovies, findDuplicateGroups, mergeCopies


def _movie(_id, imdbId, **fields):
    base = {
        "_id": _id,
        "title": "Black Rain",
        "year": 1989,
        "runtime": 125,
        "imdb": {"id": imdbId, "rating": 6.6, "votes": 100},
        "lastupdated": datetime(2015, 1, 1),
        "directors": ["Ridley Scott"],
    }
    base.update(fields)
    return base


def test_sameImdbIdIsDuplicate():
    groups = findDuplicateGroups([_movie(1, 10), _movie(2, 10), _movie(3, 11, title="Other")])
    assert [[m["_id"] for m in g] for g in groups] == [[1, 2]]


def test_homonymsWithDifferentDirectorsAreNotDuplicates():
    # Black Rain (1989): una de Ridley Scott y otra de Shōhei Imamura (A3).
    imamura = _movie(2, 11, directors=["Shèhei Imamura"])
    assert findDuplicateGroups([_movie(1, 10), imamura]) == []


def test_secondaryRuleNeedsSameRuntimeAndPeople():
    # A4: distinto imdb.id, mismo título, año, duración y directores.
    assert len(findDuplicateGroups([_movie(1, 10), _movie(2, 11, title=" black  rain")])) == 1
    assert findDuplicateGroups([_movie(1, 10), _movie(2, 11, runtime=90)]) == []
    assert findDuplicateGroups([_movie(1, 10, directors=[]), _movie(2, 11, directors=[])]) == []


def test_mostRecentCopyWins():
    old, new = _movie(1, 10), _movie(2, 10, lastupdated=datetime(2016, 1, 1))
    winner, _, losers = mergeCopies([old, new])
    assert winner["_id"] == 2 and [m["_id"] for m in losers] == [1]


def test_tieBreaksByFilledFieldsThenId():
    full, sparse = _movie(1, 10, plot="Something"), _movie(2, 10)
    assert mergeCopies([sparse, full])[0]["_id"] == 1  # más campos le gana al _id mayor
    assert mergeCopies([_movie(1, 10), _movie(2, 10)])[0]["_id"] == 2  # _id mayor


def test_winnerFillsNullsFromOtherCopies():
    winner = _movie(2, 10, lastupdated=datetime(2016, 1, 1), year=None, imdb={"id": 10, "rating": None, "votes": 100})
    other = _movie(1, 10, year=1989, imdb={"id": 10, "rating": 7.4, "votes": 90})
    merged, changes, _ = mergeCopies([winner, other])
    assert merged["year"] == 1989
    assert merged["imdb"] == {"id": 10, "rating": 7.4, "votes": 100}  # votes sigue siendo de la ganadora
    assert sorted((c.field, c.rule) for c in changes) == [("imdb.rating", "A5"), ("year", "A5")]
    assert winner["year"] is None  # no modifica la entrada


def test_listsAreTakenWholeNotMixed():
    winner = _movie(2, 10, lastupdated=datetime(2016, 1, 1), cast=["A"])
    merged, _, _ = mergeCopies([winner, _movie(1, 10, cast=["A", "B"])])
    assert merged["cast"] == ["A"]


def test_dedupeMarksEveryMovie():
    movies = [_movie(1, 10), _movie(2, 10, lastupdated=datetime(2016, 1, 1)), _movie(3, 11, title="Other")]
    result, changes, mergedInto = dedupeMovies(movies)
    byId = {m["_id"]: m for m in result}
    assert mergedInto == {1: 2}
    assert (byId[1]["deleted"], byId[1]["deletedReason"], byId[1]["mergedInto"]) == (True, "duplicateMovie", 2)
    for activeId in (2, 3):
        assert (byId[activeId]["deleted"], byId[activeId]["deletedReason"], byId[activeId]["mergedInto"]) == (False, None, None)
    assert [c.rule for c in changes[1]] == ["G2"]
    assert "deleted" not in movies[0]  # no modifica la entrada
