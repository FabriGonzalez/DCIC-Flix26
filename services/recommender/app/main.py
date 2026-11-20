"""recommender: motor de recomendaciones (docs/recomendador.md, sección 9).

    lifecycle.py  embeddings, limpieza, indexado y WR cada 60 s (9.2)
    api.py        las rutas para el backend (9.4)

/health (D12): críticas Mongo, Rabbit y la topología, más "ready", "phase", "movies" y
"votes". El código HTTP depende solo de las críticas: mientras embebe o indexa, el
servicio está sano (200) pero no listo. Si diera 503, Docker lo marcaría unhealthy
durante el embedding. Las rutas de api.py, en cambio, dan 503 hasta que hay índice.

Regla del event loop: embeber, indexar y recomendar es cálculo y va en un hilo
(asyncio.to_thread). Si bloquea el loop, /health deja de responder y aio-pika deja de
atender la conexión con Rabbit.

Ante un error irrecuperable (D14), detiene uvicorn y el proceso termina con código 1;
`restart: unless-stopped` lo vuelve a levantar.
"""

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Response

from dcicflix_common import logging as logs
from dcicflix_common.aio.service import DataService
from dcicflix_common.config import ConfigError

from app import api
from app.lifecycle import Recommender

SERVICE = "recommender"
PORT = 8000

log = logging.getLogger(SERVICE)


def create_app(on_fatal) -> FastAPI:
    data = DataService(SERVICE, on_fatal=on_fatal)
    recommender = Recommender(data, on_fatal=on_fatal)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await data.start()
        await recommender.start()
        yield
        await recommender.stop()
        await data.stop()

    app = FastAPI(title="DCIC-Flix recommender", lifespan=lifespan)

    @app.get("/health")
    async def health(response: Response) -> dict:
        response.status_code, body = data.health()
        return {**body, **recommender.state()}

    api.install(app, recommender)
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
