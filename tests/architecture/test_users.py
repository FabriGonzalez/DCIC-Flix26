"""La colección users y GET /users, sobre el sistema levantado."""

import json

import pytest

import compose

pytestmark = pytest.mark.dynamic


@pytest.fixture(scope="module", autouse=True)
def system():
    if not compose.containers():
        pytest.skip("no hay nada levantado: correr `docker compose up -d --wait`")


def get_users(query: str = "") -> dict:
    status, _, body = compose.get_from_frontend(f"/api/users{query}")
    assert status == 200, body
    return json.loads(body)


def test_estan_los_del_dataset_y_los_nuevos():
    assert get_users()["total"] == 2000 + 5


def test_los_nuevos_van_primero_y_ninguno_trae_el_email():
    items = get_users()["items"]
    assert [u["preloaded"] for u in items[:6]] == [True] * 5 + [False]
    assert all(set(u) == {"id", "name", "preloaded"} for u in items)


def test_se_busca_por_id():
    assert [u["id"] for u in get_users("?q=usr_0142")["items"]] == ["usr_0142"]
