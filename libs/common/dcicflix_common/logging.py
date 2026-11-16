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
