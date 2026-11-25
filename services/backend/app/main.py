"""backend: /health (D12), /status (status.py), /movies (catalog.py), la ficha (movie.py,
reviews.py), los votos (votes.py, publisher.py) y /users (users.py).

Críticas: Mongo, Rabbit y la topología. Informativa: el recommender. Si no está
listo, el backend sigue sano y el catálogo, navegable.

Ante un error irrecuperable (D14), detiene uvicorn y el proceso termina con código 1;
`restart: unless-stopped` lo vuelve a levantar.
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from fastapi import Body, FastAPI, Query, Response
from pymongo.errors import PyMongoError

from dcicflix_common import config
from dcicflix_common import logging as logs
from dcicflix_common.aio.service import DataService
from dcicflix_common.config import ConfigError

from app import catalog, movie, publisher, reviews, status, users, votes

SERVICE = "backend"
PORT = 8000

log = logging.getLogger(SERVICE)


def create_app(on_fatal) -> FastAPI:
    http = httpx.AsyncClient(timeout=3)
    recommender = status.RecommenderProbe(http, config.recommender_url())
    data = DataService(SERVICE, on_fatal=on_fatal, info={"recommender": recommender.check})
    user_loader = users.UserLoader(data.mongo, on_fatal=on_fatal)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await data.start()
        user_loader.start()
        yield
        await user_loader.stop()
        await data.stop()
        await http.aclose()

    app = FastAPI(title="DCIC-Flix backend", lifespan=lifespan)

    @app.get("/health")
    async def health(response: Response) -> dict:
        response.status_code, body = data.health()
        return body

    @app.get("/status")
    async def system_status(response: Response) -> dict:
        try:
            mark = await status.read_mark(data.mongo)
        except PyMongoError:
            # Sin la marca no sabemos el estado: decir "cleaning" sería inventarlo.
            response.status_code = 503
            return {"detail": "no se pudo leer la marca de limpieza"}
        return {"state": status.combine(mark, recommender.ready)}

    @app.get("/movies")
    async def list_movies(
        response: Response,
        q: str = Query("", max_length=100),
        page: int = Query(1, ge=1, le=10_000),
    ) -> dict:
        try:
            return await catalog.list_movies(data.mongo, q, page)
        except PyMongoError:
            response.status_code = 503
            return {"detail": "no se pudo leer el catálogo"}

    @app.get("/movies/{movie_id}")
    async def movie_detail(movie_id: str, response: Response) -> dict:
        try:
            found = await movie.get_movie(data.mongo, movie_id)
        except PyMongoError:
            response.status_code = 503
            return {"detail": "no se pudo leer la película"}
        if found is None:
            response.status_code = 404
            return {"detail": "no existe la película"}
        return found

    @app.get("/movies/{movie_id}/reviews")
    async def movie_reviews(movie_id: str, response: Response) -> dict:
        try:
            found = await reviews.list_reviews(data.mongo, movie_id)
        except PyMongoError:
            response.status_code = 503
            return {"detail": "no se pudieron leer las reseñas"}
        if found is None:
            response.status_code = 404
            return {"detail": "no existe la película"}
        return found

    @app.post("/movies/{movie_id}/reviews", status_code=202)
    async def vote(movie_id: str, response: Response, body: Any = Body(None)) -> dict:
        # Any: el formato lo valida Interaction, con las mismas reglas que el ingest-consumer.
        try:
            new_vote = votes.build(movie_id, body)
            await votes.submit(
                data.mongo,
                new_vote,
                recommender_ready=recommender.ready,
                users_loaded=user_loader.loaded,
                publish=lambda v: publisher.publish(data.rabbit, v),
            )
        except votes.Rejected as exc:
            if exc.status_code == 503:
                log.warning("voto rechazado: %s (%s)", exc.detail, exc.__cause__)
            response.status_code = exc.status_code
            return {"detail": exc.detail}
        except PyMongoError:
            response.status_code = 503
            return {"detail": "no se pudo comprobar el voto"}
        return votes.to_response(new_vote)

    @app.get("/users")
    async def list_users(response: Response, q: str = Query("", max_length=100)) -> dict:
        if not user_loader.loaded:
            response.status_code = 503
            return {"detail": "los usuarios se están cargando"}
        try:
            return await users.list_users(data.mongo, q)
        except PyMongoError:
            response.status_code = 503
            return {"detail": "no se pudieron leer los usuarios"}

    return app


def main() -> None:
    logs.setup(SERVICE)
    exit_code = 0
    server: uvicorn.Server | None = None

    def on_fatal(exc: BaseException) -> None:
        nonlocal exit_code
        log.error("error irrecuperable, termino: %s: %s", type(exc).__name__, exc)
        exit_code = 1
        server.should_exit = True  # uvicorn cierra en orden: lifespan, conexiones

    try:
        app = create_app(on_fatal)
    except ConfigError as exc:
        log.error("error irrecuperable, termino: %s", exc)
        sys.exit(1)
    # log_config=None: los logs de uvicorn salen con el formato común.
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_config=None))
    server.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
