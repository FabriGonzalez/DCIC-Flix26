"""Formato de logs común: hora, nivel, servicio y módulo."""

import logging
import sys

from dcicflix_common import config


def setup(service: str) -> None:
    logging.basicConfig(
        level=config.log_level(),
        stream=sys.stdout,
        format=f"%(asctime)s %(levelname)-7s [{service}] %(name)s: %(message)s",
        force=True,
    )
    # pika registra cada intento de conexión fallido como ERROR, con traceback completo.
    # El helper ya informa cada reintento y cada error en una línea.
    logging.getLogger("pika").setLevel(logging.CRITICAL)
    # httpx loguea cada pedido como INFO: el backend consulta al recommender cada 10 s.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Docker pide /health cada 10 s: sin este filtro, el access log de uvicorn es solo eso.
    logging.getLogger("uvicorn.access").addFilter(_HideHealthRequests())


class _HideHealthRequests(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn loguea el acceso con args (cliente, método, ruta, versión HTTP, código).
        args = record.args if isinstance(record.args, tuple) else ()
        return not (len(args) >= 3 and args[2] == "/health")
