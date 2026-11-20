# Contexto de build: la raíz del repo (D4).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY libs/common /libs/common
RUN pip install "/libs/common[async]"

COPY services/recommender/requirements.txt .
RUN pip install -r requirements.txt

# Modelo de embeddings (R14): se descarga acá, con la red del build. Va antes que el resto
# del código para que cambiar un módulo no lo vuelva a descargar.
COPY services/recommender/app/__init__.py services/recommender/app/model.py ./app/
# chmod: huggingface_hub deja algunos archivos solo para root, y el servicio corre como nobody.
RUN python -m app.model && chmod -R a+rX /opt/models
# En ejecución no hay internet (internal-net): sin esto, una falta del modelo se vería
# como un timeout de red en lugar de "no está el archivo".
ENV HF_HUB_OFFLINE=1

# Volumen recommender-cache: al montarlo vacío por primera vez, Docker copia el dueño
# de esta carpeta, así nobody puede escribir los embeddings.
RUN mkdir /cache && chown nobody:nogroup /cache

COPY services/recommender/app ./app

USER nobody
CMD ["python", "-m", "app.main"]
