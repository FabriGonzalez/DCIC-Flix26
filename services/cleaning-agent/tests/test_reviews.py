"""Reglas de campo de reviews, con los casos reales que se vieron en el notebook."""

from datetime import datetime

import pytest

from app.reviews import UPDATE_PREFIX, cleanReview, isAnonymous, isUsefulComment, parseDate, parseRating, starsInText

DATASET_CREATED = datetime(2026, 11, 10, 19, 49, 18)


@pytest.mark.parametrize(("raw", "expected"), [(4, 4), ("4", 4), (10, None), (0, None), (-1, None), (6, None), (None, None)])
def test_parseRating(raw, expected):
    assert parseRating(raw) == expected


@pytest.mark.parametrize(
    ("comment", "expected"),
    [("Solid film, 4 stars from me.", 4), ("A 3-star movie at best", 3), ("10 stars!", None), ("no rating here", None)],
)
def test_starsInText(comment, expected):
    assert starsInText(comment) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (datetime(2020, 5, 1, 10, 30), (datetime(2020, 5, 1, 10, 30), "day")),
        (1588329000000, (datetime(2020, 5, 1, 10, 30), "day")),  # epoch en ms
        ("25/12/2019", (datetime(2019, 12, 25), "day")),  # dd/mm
        ("2019-12-25", (datetime(2019, 12, 25), "day")),
        ("circa 2023", (datetime(2023, 1, 1), "year")),
        ("yesterday", (None, None)),
    ],
)
def test_parseDate(raw, expected):
    assert parseDate(raw) == expected


def _review(**fields):
    base = {"user_id": "usr_0001", "rating": 4, "comment": "A long enough comment.", "date": datetime(2020, 1, 1)}
    base.update(fields)
    return base


def test_futureDateBecomesNull():
    doc, changes = cleanReview(_review(date=datetime(2027, 1, 1)), DATASET_CREATED)
    assert (doc["date"], doc["datePrecision"]) == (None, None)
    assert [c.rule for c in changes] == ["B10"]


def test_unknownDateHasNoPrecision():
    doc, changes = cleanReview(_review(date="yesterday"), DATASET_CREATED)
    assert (doc["date"], doc["datePrecision"]) == (None, None)
    assert [c.rule for c in changes] == ["B9"]


def test_circaKeepsYearPrecision():
    doc, _ = cleanReview(_review(date="circa 2023"), DATASET_CREATED)
    assert (doc["date"], doc["datePrecision"]) == (datetime(2023, 1, 1), "year")


def test_validReviewHasNoChanges():
    doc, changes = cleanReview(_review(), DATASET_CREATED)
    assert changes == []
    assert doc["datePrecision"] == "day"


def test_textRatingIsB14():
    _, changes = cleanReview(_review(rating="5"), DATASET_CREATED)
    assert [(c.rule, c.before, c.after) for c in changes] == [("B14", "5", 5)]


def test_invalidRatingRecoveredFromText():
    doc, changes = cleanReview(_review(rating=10, comment="Loved it, 4 stars."), DATASET_CREATED)
    assert doc["rating"] == 4
    assert [(c.rule, c.after) for c in changes] == [("B5", None), ("B6", 4)]


def test_invalidRatingWithoutStarsWaitsForLlm():
    doc, _ = cleanReview(_review(rating=999), DATASET_CREATED)
    assert doc["rating"] is None


def test_cleanReviewDoesNotMutateInput():
    raw = _review(rating="3")
    cleanReview(raw, DATASET_CREATED)
    assert raw["rating"] == "3" and "datePrecision" not in raw


@pytest.mark.parametrize(("userId", "expected"), [("usr_0001", False), ("usr_0000", True), ("", True), (None, True)])
def test_isAnonymous(userId, expected):
    assert isAnonymous({"user_id": userId}) is expected


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("A long enough comment.", True),
        ("", False),
        ("...", False),
        ("asdf", False),
        ("nice", False),
        (f"{UPDATE_PREFIX} ok", False),  # el prefijo no cuenta como contenido
        (f"{UPDATE_PREFIX} Much better the second time.", True),
        (None, False),
    ],
)
def test_isUsefulComment(comment, expected):
    assert isUsefulComment(comment) is expected
