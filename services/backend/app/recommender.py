"""Pedidos a la API del recommender (docs/recomendador.md 9.4), con un solo manejo de errores."""

import httpx


class RecommenderUnavailable(Exception):
    """El recommender no respondió, o respondió algo que no es 200 ni un 404 esperado (503: sin índice)."""


async def get(http: httpx.AsyncClient, url: str, path: str, params: dict | None = None, *, missing_ok: bool = False) -> dict | None:
    """El JSON de la respuesta. Con missing_ok, un 404 devuelve None en vez de lanzar."""
    try:
        response = await http.get(f"{url}{path}", params=params)
    except httpx.HTTPError as exc:
        raise RecommenderUnavailable(f"{path}: {type(exc).__name__}") from exc
    if response.status_code == 404 and missing_ok:
        return None
    if response.status_code != 200:
        raise RecommenderUnavailable(f"{path}: HTTP {response.status_code}")
    return response.json()
