"""Modelo de embeddings del plot (R14, docs/recomendador.md 4.4).

Se descarga en el `docker build` con `python -m app.model`: los RUN usan la red del
build, que tiene internet. En ejecución el contenedor está en internal-net, sin salida,
así que el modelo se carga de DIR sin tocar la red (local_files_only).

Este archivo se copia a la imagen antes que el resto del código: cambiar otro módulo
no invalida la capa del modelo ni lo vuelve a descargar.
"""

from fastembed import TextEmbedding

NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIR = "/opt/models"
DIM = 384


def load(*, offline: bool = True) -> TextEmbedding:
    return TextEmbedding(NAME, cache_dir=DIR, local_files_only=offline)


if __name__ == "__main__":
    # Descarga y prueba: si el modelo no embebe, el build falla acá y no en ejecución.
    vector = next(iter(load(offline=False).embed(["A test plot."])))
    assert vector.shape == (DIM,), vector.shape
    print(f"modelo {NAME} en {DIR}: {DIM} dimensiones")
