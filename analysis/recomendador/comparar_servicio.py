"""Compara el código del servicio contra pesos.py (docs/recomendador.md, sección 9).

Corre services/recommender/app/index.py y recommend.py, el mismo código del contenedor,
sobre el dataset crudo. Prepara los datos como pesos.py (una copia por imdb.id y los
campos llevados al contrato limpio) y repite su prueba de conjuntos escondidos, con
los pesos, β y λ decididos. Lo esperado (6.3): calibración 0,461 / 1,000 / 0,195 y
recall@20 ≈ 83,5 %.

Lee los vectores de la caché del servicio (plots.npz, por hash del plot) y deja
plots.npy en la misma carpeta, en el orden de movies.json.gz, para correr pesos.py
con los mismos vectores.

Uso: python -I -X utf8 comparar_servicio.py movies.json.gz reviews.json.gz cache/plots.npz
     (la caché sale del contenedor: docker cp dcicflix-recommender-1:/cache/plots.npz ...)
"""
import collections, gzip, hashlib, json, random, re, statistics, sys, time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "recommender"))
from app import params  # noqa: E402
from app.index import _dot, build_catalog, build_quality, strip_role  # noqa: E402
from app.recommend import for_user, from_weights  # noqa: E402

movies_gz, reviews_gz, cache_path = sys.argv[1:4]
crudo = [json.loads(l) for l in gzip.open(movies_gz, "rt", encoding="utf-8")]

# --- Vectores: los de la caché del servicio, por hash del plot ---
with np.load(cache_path) as data:
    fila_hash = {h.tobytes(): i for i, h in enumerate(data["hashes"])}
    vectores = data["vectors"]
def vector(plot):
    if not isinstance(plot, str) or not plot.strip():
        return np.zeros(vectores.shape[1], np.float32)
    return vectores[fila_hash[hashlib.sha256(plot.encode("utf-8")).digest()]]
Vall = np.array([vector(d.get("plot")) for d in crudo], dtype=np.float32)
np.save(Path(cache_path).with_name("plots.npy"), Vall)

# --- Una copia por imdb.id, igual que pesos.py ---
vistos, keep = set(), []
for i, d in enumerate(crudo):
    if d["imdb"]["id"] not in vistos:
        vistos.add(d["imdb"]["id"]); keep.append(i)
movs = [crudo[i] for i in keep]
N = len(movs)
primera = {d["imdb"]["id"]: j for j, d in enumerate(movs)}
idmap = {d["_id"]["$oid"]: primera[d["imdb"]["id"]] for d in crudo}

# --- Campos llevados al contrato, con las mismas reglas que pesos.py ---
def num(x):
    if isinstance(x, str):
        x = x.replace(",", "").strip()
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
def generos(d):
    g = d.get("genres")
    if isinstance(g, str):
        g = re.split(r" / |\||, ", g)
    return sorted({x.strip() for x in g}) if g else None
def contrato(d):
    r, v = num(d["imdb"].get("rating")), num(d["imdb"].get("votes"))
    if r in (14.5, -1):
        r = None
    if r is not None and r > 10:
        r /= 10
    imdb = {"rating": r, "votes": v} if r is not None and v is not None else None
    doc = {"_id": d["_id"]["$oid"], "genres": generos(d), "imdb": imdb}
    for campo in ("directors", "cast", "writers"):
        doc[campo] = d.get(campo)
    return doc

t = time.time()
catalog = build_catalog([contrato(d) for d in movs], Vall[keep])
t_catalogo = time.time() - t
qp, qg, qt = catalog.scales
print(f"catálogo: {N} películas, {len(catalog.genres)} géneros, {catalog.T.shape[1]} personas | {t_catalogo:.1f} s")
print(f"calibración: plot {qp:.3f} | géneros {qg:.3f} | personas {qt:.3f}   (doc: 0,461 | 1,000 | 0,195)")
print(f"valores fuera de contrato: {dict(catalog.anomalies) or 'ninguno'}")

# --- Votos, con el mismo filtro que pesos.py ---
counts, sums = np.zeros(N), np.zeros(N)
votos_usuario = collections.defaultdict(list)
for l in gzip.open(reviews_gz, "rt", encoding="utf-8"):
    rv = json.loads(l); rt = rv.get("rating"); u = rv.get("user_id")
    if isinstance(rt, str) and rt.isdigit():
        rt = int(rt)
    if isinstance(rt, int) and 1 <= rt <= 5 and u and u != "usr_0000" and rv["movie_id"]["$oid"] in idmap:
        j = idmap[rv["movie_id"]["$oid"]]
        counts[j] += 1; sums[j] += rt
        votos_usuario[u].append((j, rt))
t = time.time()
quality = build_quality(catalog, counts, sums)
t_calidad = time.time() - t
a, b = quality.q5
print(f"WR: C {quality.mean_vote:.3f}, Q₅ = {a:.2f}·Q + {b:.2f}, media {quality.wr.mean():.2f}, "
      f"desvío {quality.wr.std():.2f} | {quality.votes} votos | {t_calidad * 1000:.0f} ms   "
      f"(doc: C 3,525, Q₅ = 0,53·Q − 0,18, media 3,41, desvío 0,37)")

# --- Conjuntos escondidos: el código de pesos.py, sin cambios ---
rng = random.Random(2026)
sin_rol = strip_role
Gs = [frozenset(generos(d) or ()) for d in movs]
por_dir = collections.defaultdict(list)
for i, d in enumerate(movs):
    ds = d.get("directors") or []
    if ds:
        por_dir[sin_rol(ds[0])].append(i)
dirs = [v for v in por_dir.values() if len(v) >= 6]
ROM = r"(?:ii|iii|iv|v|vi|vii|viii|ix|x)"
def base(t):
    t = t.strip().lower()
    t = re.sub(r"\s*[:\-–]\s*(part|chapter|episode)\s+\w+.*$", "", t)
    t = re.sub(rf"\s+(part\s+)?([2-9]|1[0-9]|{ROM})\b.*$", "", t)
    t = re.sub(r"\s*:.*$", "", t)
    return t.strip()
por_base = collections.defaultdict(list)
for i, d in enumerate(movs):
    por_base[base(d["title"])].append(i)
sagas = [v for k, v in por_base.items() if len(k) >= 4 and len(v) >= 4 and len({movs[i]["title"].strip() for i in v}) >= 3]
por_combo = collections.defaultdict(list)
for i, s in enumerate(Gs):
    if len(s) >= 3:
        por_combo[s].append(i)
combos = [v for v in por_combo.values() if 6 <= len(v) <= 40]
tipos = {}
for nombre, grupos in (("director", dirs), ("saga", sagas), ("géneros", combos)):
    grupos = rng.sample(grupos, min(200, len(grupos)))
    casos = []
    for g in grupos:
        votadas = rng.sample(g, 3)
        casos.append((votadas, [i for i in g if i not in votadas]))
    tipos[nombre] = casos

# --- La calibración de pesos.py, con su misma muestra, para comparar el método ---
muestra = rng.sample(range(N), 1000)
def escala_pesos(X, exacta):
    x = _dot(X[muestra], X)
    x[np.arange(len(muestra)), muestra] = 0
    d10 = -np.partition(-x, 9 if exacta else 10, axis=1)[:, 9]
    return float(np.median(d10[d10 > 0]))
for exacta, etiqueta in ((False, "pesos.py (partition 10, columna 9)"), (True, "10.º exacto (partition 9)")):
    e = [escala_pesos(X, exacta) for X in (catalog.plot, catalog.G, catalog.T)]
    print(f"calibración con la muestra de pesos.py, {etiqueta}: " + " | ".join(f"{x:.3f}" for x in e))

# --- Recall@20 con el código del servicio ---
def evaluar(recomendar):
    res = {}
    for nombre, casos in tipos.items():
        rec = []
        for vot, ocultas in casos:
            top = {item.row for item in recomendar(vot)}
            rec.append(len(top & set(ocultas)) / min(len(ocultas), 20))
        res[nombre] = statistics.mean(rec)
    return statistics.mean(res.values()), res
print()
for etiqueta, recomendar in (
    ("peso 1 por voto, como pesos.py", lambda vot: from_weights(catalog, quality, [(i, 1.0) for i in vot], 20)[1]),
    ("3 votos de 5 ★, como un usuario", lambda vot: for_user(catalog, quality, [(i, 5) for i in vot], 20)[1]),
):
    prom, res = evaluar(recomendar)
    det = " | ".join(f"{k} {100 * v:.1f}" for k, v in res.items())
    print(f"recall@20, {etiqueta}: {100 * prom:.1f} %  ({det})   (doc: 83,5 %)")

# --- Tiempo por petición, con 300 usuarios del dataset (7.1) ---
usuarios = random.Random(7).sample(sorted(votos_usuario), 300)
tiempos = []
for u in usuarios:
    t = time.perf_counter()
    for_user(catalog, quality, votos_usuario[u], 20)
    tiempos.append((time.perf_counter() - t) * 1000)
tiempos.sort()
print(f"\n'Recomendadas para vos', 300 usuarios: mediana {statistics.median(tiempos):.1f} ms, "
      f"p95 {tiempos[int(0.95 * len(tiempos))]:.1f} ms   (doc: 8 / 19 ms)")
