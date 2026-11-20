"""Descarga el modelo, embebe todos los plots del crudo y guarda los vectores (R14, R17).

Respalda docs/recomendador.md, sección 4.4 (tiempos y tamaños). Los demás scripts leen el
archivo que deja: <carpeta>/plots.npy, una fila por película en el orden de movies.json.gz.

Uso: python -I -X utf8 embeber.py movies.json.gz <carpeta de caché>   (≈ 6 min en 4 CPUs)
"""
import gzip, json, os, sys, time

import numpy as np
from fastembed import TextEmbedding

movies_gz, cache = sys.argv[1], sys.argv[2]
plots = [json.loads(l)["plot"] for l in gzip.open(movies_gz, "rt", encoding="utf-8")]

t0 = time.time()
model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2", cache_dir=cache)
t1 = time.time()
size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(cache) for f in fs)
print(f"descarga + carga del modelo: {t1 - t0:.1f} s, {size / 1e6:.0f} MB en disco")

V = np.array(list(model.embed(plots, batch_size=256)), dtype=np.float32)
t2 = time.time()
print(f"embedding de {len(plots)} plots: {t2 - t1:.1f} s, dimensión {V.shape[1]}, cpus {os.cpu_count()}")
np.save(os.path.join(cache, "plots.npy"), V)
