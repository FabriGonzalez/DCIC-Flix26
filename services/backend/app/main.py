"""backend: /health (D12) y /status (status.py).

Críticas: Mongo, Rabbit y la topología. Informativa: el recommender. Si no está
listo, el backend sigue sano y el catálogo, navegable.

Ante un error irrecuperable (D14), detiene uvicorn y el proceso termina con código 1;
`restart: unless-stopped` lo vuelve a levantar.
"""

import logging
import sys
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Response
from pymongo.errors import PyMongoError

from dcicflix_common import config
from dcicflix_common import logging as logs
from dcicflix_common.aio.service import DataService
from dcicflix_common.config import ConfigError

from app import status

SERVICE = "backend"
PORT = 8000

log = logging.getLogger(SERVICE)


def create_app(on_fatal) -> FastAPI:
    http = httpx.AsyncClient(timeout=3)
    recommender = status.RecommenderProbe(http, config.recommender_url())
    data = DataService(SERVICE, on_fatal=on_fatal, info={"recommender": recommender.check})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await data.start()
        yield
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
