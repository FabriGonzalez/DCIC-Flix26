"""¿El embedding del plot es una señal útil? (docs/recomendador.md, sección 4.1)

Para 2.000 películas al azar: ¿sus 10 vecinas por plot comparten algún género más seguido que 10
películas al azar? Se excluyen las copias con el mismo imdb.id. Imprime también vecinas de ejemplo.

Uso: python -I -X utf8 senal_plot.py movies.json.gz cache/plots.npy
"""
import gzip, json, random, re, sys

import numpy as np

movies_gz, vec_path = sys.argv[1], sys.argv[2]

movs = [json.loads(l) for l in gzip.open(movies_gz, "rt", encoding="utf-8")]
ids = [d["_id"]["$oid"] for d in movs]

V = np.load(vec_path)
V /= np.linalg.norm(V, axis=1, keepdims=True)

# Géneros con la regla P3 aplicada (texto -> lista, recorte).
def generos(d):
    g = d.get("genres")
    if isinstance(g, str):
        g = re.split(r" / |\||, ", g)
    return {x.strip() for x in g} if g else set()
G = [generos(d) for d in movs]

# 1. Vecinos por plot. Se excluyen las copias con el mismo imdb.id (darían similitud trivial).
imdb = [d["imdb"]["id"] for d in movs]
rng = random.Random(2026)
muestra = [i for i in rng.sample(range(len(movs)), 2000) if G[i]]
k = 10
comp_vec = comp_azar = tot = 0
for i in muestra:
    s = V @ V[i]
    s[[j for j in range(len(movs)) if imdb[j] == imdb[i]]] = -2
    vecinos = np.argpartition(-s, k)[:k]
    azar = rng.sample(range(len(movs)), k)
    comp_vec += sum(bool(G[i] & G[j]) for j in vecinos)
    comp_azar += sum(bool(G[i] & G[j]) for j in azar if imdb[j] != imdb[i])
    tot += k
print(f"1. comparten >=1 genero: vecinos por plot {100*comp_vec/tot:.1f} %  vs azar {100*comp_azar/tot:.1f} %")

# Un ejemplo para mirar a ojo.
idx = {t: i for i, t in enumerate(d["title"].strip() for d in movs)}
for titulo in ("The Godfather", "Toy Story", "Alien"):
    if titulo in idx:
        i = idx[titulo]
        s = V @ V[i]
        s[[j for j in range(len(movs)) if imdb[j] == imdb[i]]] = -2
        top = np.argsort(-s)[:5]
        print(f"   {titulo}: " + "; ".join(movs[j]["title"].strip() for j in top))
