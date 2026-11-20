"""Reseñas entre documentos: G2, B4, B11, B13, B12, B7/B8 y A16."""

from datetime import datetime

from app.reviews import UPDATE_PREFIX
from app.votes import countVisibleComments, pickWinnerVote, resolveReviews

RELEASED = datetime(2000, 1, 1)
COMMENT = "A long enough comment."


def _movie(_id, deleted=False):
    return {"_id": _id, "released": RELEASED, "deleted": deleted}


def _review(_id, movieId="m1", userId="usr_0001", **fields):
    base = {"_id": _id, "movie_id": movieId, "user_id": userId, "rating": 4, "comment": COMMENT, "date": datetime(2020, 1, 1)}
    base.update(fields)
    return base


def _resolve(reviews, movies=None, mergedInto=None):
    result, changes = resolveReviews(movies or [_movie("m1")], reviews, mergedInto or {})
    return {r["_id"]: r for r in result}, changes


def test_activeReviewGetsDefaultFlags():
    byId, changes = _resolve([_review(1)])
    assert (byId[1]["deleted"], byId[1]["deletedReason"], byId[1]["commentHidden"]) == (False, None, False)
    assert changes == {}


def test_reviewOfDiscardedCopyIsReassigned():
    movies = [_movie("m1"), _movie("m2", deleted=True)]
    byId, changes = _resolve([_review(1, movieId="m2")], movies, {"m2": "m1"})
    assert byId[1]["movie_id"] == "m1" and not byId[1]["deleted"]
    assert [(c.rule, c.before, c.after) for c in changes[1]] == [("G2", "m2", "m1")]


def test_anonymousAndOrphanAreDeleted():
    byId, _ = _resolve([_review(1, userId="usr_0000"), _review(2, userId=""), _review(3, movieId="nope")])
    assert [byId[i]["deletedReason"] for i in (1, 2, 3)] == ["anonymous", "anonymous", "orphan"]


def test_latestValidVoteWins():
    old, new = _review(1, date=datetime(2020, 1, 1)), _review(2, date=datetime(2021, 1, 1))
    byId, _ = _resolve([old, new])
    assert (byId[1]["deletedReason"], byId[2]["deleted"]) == ("duplicateVote", False)


def test_dateBeforeReleaseIsNotValid():
    beforeRelease = _review(1, date=datetime(1990, 1, 1))
    assert pickWinnerVote([beforeRelease, _review(2, date=None)], RELEASED)["_id"] == 2


def test_updateBreaksDateTie():
    same = datetime(2020, 1, 1)
    update = _review(1, date=same, comment=f"{UPDATE_PREFIX} Much better now.")
    assert pickWinnerVote([update, _review(2, date=same)], RELEASED)["_id"] == 1


def test_identicalCopiesKeepHighestId():
    assert pickWinnerVote([_review(1), _review(2)], RELEASED)["_id"] == 2


def test_votesOnTwoCopiesBecomeDuplicateAfterReassigning():
    movies = [_movie("m1"), _movie("m2", deleted=True)]
    byId, _ = _resolve([_review(1, movieId="m1"), _review(2, movieId="m2", date=datetime(2021, 1, 1))], movies, {"m2": "m1"})
    assert (byId[1]["deletedReason"], byId[2]["deleted"]) == ("duplicateVote", False)


def test_junkCommentIsHiddenButVoteStays():
    byId, changes = _resolve([_review(1, comment="asdf")])
    assert (byId[1]["commentHidden"], byId[1]["deleted"]) == (True, False)
    assert [c.rule for c in changes[1]] == ["B7"]


def test_noRatingAndNoCommentIsDeleted():
    byId, _ = _resolve([_review(1, rating=None, comment="ok"), _review(2, rating=None, userId="usr_0002")])
    assert byId[1]["deletedReason"] == "noContent"
    assert not byId[2]["deleted"]  # comentario útil: el rating lo infiere el LLM


def test_countVisibleComments():
    movies = [_movie("m1"), _movie("m2", deleted=True)]
    reviews = [
        {"movie_id": "m1", "deleted": False, "commentHidden": False},
        {"movie_id": "m1", "deleted": False, "commentHidden": True},
        {"movie_id": "m1", "deleted": True, "commentHidden": False},
    ]
    result, changes = countVisibleComments(movies, reviews)
    assert [m["num_mflix_comments"] for m in result] == [1, 0]
    assert [c.rule for c in changes["m1"]] == ["A16"]
    assert "num_mflix_comments" not in movies[0]
