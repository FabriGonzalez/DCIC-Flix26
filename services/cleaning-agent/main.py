"""cleaning-agent: stub conectado (D1).

Por ahora solo se conecta a Mongo y a Rabbit, verifica la topología y escribe el
latido. Más adelante limpia el dataset y publica en `data.cleaned`.
"""

import logging

from dcicflix_common import config
from dcicflix_common import logging as logs
from dcicflix_common.sync import worker

SERVICE = "cleaning-agent"

if __name__ == "__main__":
    logs.setup(SERVICE)
    # Sin API key la app funciona: la limpieza con LLM queda deshabilitada (D15).
    if config.llm_api_key() is None:
        logging.getLogger(SERVICE).warning("sin LLM_API_KEY: la limpieza con LLM queda deshabilitada")
    worker.main(SERVICE)
