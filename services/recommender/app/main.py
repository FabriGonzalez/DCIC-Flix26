"""recommender: stub conectado (D1) con /health (D12).

Críticas: Mongo, Rabbit y la topología. Más adelante, /health agrega "ready" y el
servicio consume `data.cleaned` para entrenar.

Regla del event loop: el entrenamiento es cálculo pesado y va en un proceso o hilo
aparte (run_in_executor). Si bloquea el loop, /health deja de responder y aio-pika
deja de atender la conexión con Rabbit.

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

SERVICE = "recommender"
PORT = 8000

log = logging.getLogger(SERVICE)


def create_app(on_fatal) -> FastAPI:
    data = DataService(SERVICE, on_fatal=on_fatal)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await data.start()
        yield
        await data.stop()

    app = FastAPI(title="DCIC-Flix recommender", lifespan=lifespan)

    @app.get("/health")
    async def health(response: Response) -> dict:
        response.status_code, body = data.health()
        return body

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
