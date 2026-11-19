# Contexto de build: la raíz del repo (D4).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY libs/common /libs/common
RUN pip install "/libs/common[sync]"

COPY services/ingest-consumer/main.py .

USER nobody
CMD ["python", "main.py"]
