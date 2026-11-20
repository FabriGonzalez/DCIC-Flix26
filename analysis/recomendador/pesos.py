"""Pesos de las señales (R9), piso de calidad β y λ de MMR (R19) con la prueba de conjuntos
escondidos. Respalda docs/recomendador.md, secciones 4.1, 4.3 y 6.3.

Conjunto = películas que "van juntas" (mismo director, saga o combinación rara de géneros).
Un usuario ficticio vota 3 con 5 estrellas; se mide qué parte del resto aparece en su top 20
(recall@20), recomendando con vecinos precalculados (K = 100) como en R15.

Criterios (todos "conservar al menos el 90 % del recall de referencia"):
  1. Pesos: grilla con paso 0,1. Al plot se le da el MAYOR peso cuya mejor combinación conserve el
     90 % del recall máximo, porque la prueba no puede medir lo que aporta el plot (ver 6.3).
  2. β: el mayor valor que conserve el 90 % del recall sin β.
  3. λ: se imprime la tabla; el valor elegido (0,8) es por criterio, no por la regla del 90 %.

Uso: python -I -X utf8 pesos.py movies.json.gz reviews.json.gz cache/plots.npy   (≈ 1,5 min)
"""
import collections, gzip, json, math, random, re, statistics, sys, time

import numpy as np
from scipy import sparse

movies_gz, reviews_gz, vec_path = sys.argv[1:4]
t_inicio = time.time()
crudo = [json.loads(l) for l in gzip.open(movies_gz, "rt", encoding="utf-8")]
Vall = np.load(vec_path).astype(np.float32)

# Una copia por imdb.id (aproxima la fusión de duplicados de la limpieza).
vistos, keep = set(), []
for i, d in enumerate(crudo):
    if d["imdb"]["id"] not in vistos:
        vistos.add(d["imdb"]["id"]); keep.append(i)
movs = [crudo[i] for i in keep]
N = len(movs)
P = Vall[keep]; P /= np.linalg.norm(P, axis=1, keepdims=True)
pos = {d["_id"]["$oid"]: i for i, d in enumerate(movs)}
primera = {}  # cualquier copia -> índice de la que quedó
for j, d in enumerate(movs):
    primera[d["imdb"]["id"]] = j
idmap = {d["_id"]["$oid"]: primera[d["imdb"]["id"]] for d in crudo}

def generos(d):
    g = d.get("genres")
    if isinstance(g, str):
        g = re.split(r" / |\||, ", g)
    return frozenset(x.strip() for x in g) if g else frozenset()
Gs = [generos(d) for d in movs]
gidx = {g: k for k, g in enumerate(sorted({g for s in Gs for g in s}))}
G = np.zeros((N, len(gidx)), np.float32)
for i, s in enumerate(Gs):
    for g in s:
        G[i, gidx[g]] = 1
G /= np.maximum(np.linalg.norm(G, axis=1, keepdims=True), 1e-9)

sin_rol = lambda x: re.sub(r"\s*\(.*$", "", x).strip()
Ps = [{sin_rol(x) for f in ("directors", "cast", "writers") for x in (d.get(f) or [])} for d in movs]
df = collections.Counter(n for s in Ps for n in s)
pidx = {n: k for k, n in enumerate(n for n, c in df.items() if c >= 2)}
r_, c_, v_ = [], [], []
for i, s in enumerate(Ps):
    for n in s:
        if n in pidx:
            r_.append(i); c_.append(pidx[n]); v_.append(math.log(N / df[n]))
T = sparse.csr_matrix((v_, (r_, c_)), shape=(N, len(pidx)), dtype=np.float32)
nT = np.sqrt(np.asarray(T.multiply(T).sum(axis=1)).ravel())
T = sparse.diags(1 / np.maximum(nT, 1e-9)).dot(T).tocsr()
Tt = T.T.tocsr()

# --- WR con R4/R5: M = 3.000, m = 5, pasaje a 1-5 por regresión ---
def num(x):
    if isinstance(x, str):
        x = x.replace(",", "").strip()
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
R, Vv = [], []
for d in movs:
    r, v = num(d["imdb"].get("rating")), num(d["imdb"].get("votes"))
    if r in (14.5, -1):
        r = None
    if r is not None and r > 10:
        r /= 10
    if v is None:
        r = None
    R.append(r); Vv.append(v)
Ci = statistics.mean(r for r in R if r is not None)
Q = [(v * r + 3000 * Ci) / (v + 3000) if r is not None else None for r, v in zip(R, Vv)]
own = collections.defaultdict(list)
for l in gzip.open(reviews_gz, "rt", encoding="utf-8"):
    rv = json.loads(l); rt = rv.get("rating"); u = rv.get("user_id")
    if isinstance(rt, str) and rt.isdigit():
        rt = int(rt)
    if isinstance(rt, int) and 1 <= rt <= 5 and u and u != "usr_0000" and rv["movie_id"]["$oid"] in idmap:
        own[idmap[rv["movie_id"]["$oid"]]].append(rt)
C = statistics.mean(x for v in own.values() for x in v)
xs = [Q[j] for j, v in own.items() for _ in v if Q[j] is not None]
ys = [x for j, v in own.items() for x in v if Q[j] is not None]
a, b = np.polyfit(xs, ys, 1)
WR = np.array([(sum(own.get(j, [])) + 5 * ((a * Q[j] + b) if Q[j] is not None else C)) / (len(own.get(j, [])) + 5) for j in range(N)], np.float32)
WRz = (WR - WR.mean()) / WR.std()
print(f"catálogo sin duplicados: {N} películas | WR: media {WR.mean():.2f}, desvío {WR.std():.2f}")

# --- Conjuntos ---
rng = random.Random(2026)
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
    print(f"conjuntos '{nombre}': {len(grupos)} | ejemplo: " +
          "; ".join(movs[i]["title"].strip() for i in casos[0][0] + casos[0][1][:2]))
print(f"   disponibles: director {len(dirs)}, saga {len(sagas)}, géneros {len(combos)}")

# --- Similitud por señal, solo para las películas votadas en la prueba ---
filas = sorted({i for casos in tipos.values() for vot, _ in casos for i in vot})
fila = {i: k for k, i in enumerate(filas)}
Sp = P[filas] @ P.T
Sg = G[filas] @ G.T
St = (T[filas] @ Tt).toarray()
for S in (Sp, Sg, St):
    S[np.arange(len(filas)), filas] = 0

# Calibración: cada señal se divide por el valor típico de un "buen vecino" según esa señal
# (mediana, sobre 1.000 películas al azar, de su 10.º valor más alto).
muestra = rng.sample(range(N), 1000)
def escala(M_):
    x = M_[muestra] @ M_.T if not sparse.issparse(M_) else (M_[muestra] @ M_.T).toarray()
    x[np.arange(len(muestra)), muestra] = 0
    d10 = -np.partition(-x, 10, axis=1)[:, 9]
    d10 = d10[d10 > 0]
    return float(np.median(d10)), 100 * len(d10) / len(muestra)
qp, _ = escala(P); qg, _ = escala(G); qt, ft = escala(T)
print(f"calibración (10.º vecino típico): plot {qp:.3f} | géneros {qg:.3f} | personas {qt:.3f} "
      f"(solo el {ft:.0f} % de las películas tiene 10 vecinos por personas)")
Sp /= qp; Sg /= qg; St /= qt
St = np.minimum(St, 2.0)  # tope: una coincidencia de personas no tapa todo lo demás

K = 100
def evaluar(w, beta=0.0, lam=1.0, n=20):
    S = w[0] * Sp + w[1] * Sg + w[2] * St
    top = np.argpartition(-S, K, axis=1)[:, :K]
    vals = np.take_along_axis(S, top, axis=1)
    res = {}
    for nombre, casos in tipos.items():
        rec, cal, div = [], [], []
        for vot, ocultas in casos:
            acc = collections.defaultdict(float)
            for i in vot:
                for j, s in zip(top[fila[i]], vals[fila[i]]):
                    if j not in vot:
                        acc[j] += s
            cands = np.array(sorted(acc, key=lambda j: -acc[j])[:200])
            sc = np.array([acc[j] for j in cands]) + beta * WRz[cands]
            orden = np.argsort(-sc); cands, sc = cands[orden], sc[orden]
            if lam < 1.0:
                sim = w[0] * (P[cands] @ P[cands].T) / qp + w[1] * (G[cands] @ G[cands].T) / qg + \
                      w[2] * np.minimum((T[cands] @ T[cands].T).toarray() / qt, 2.0)
                scn = (sc - sc.min()) / (sc.max() - sc.min() + 1e-9)
                simn = sim / (np.abs(sim).max() + 1e-9)
                elegidos, maxsim = [], np.full(len(cands), -np.inf)
                libres = np.ones(len(cands), bool)
                for _ in range(min(n, len(cands))):
                    pen = np.where(np.isinf(maxsim), 0, maxsim)
                    val = np.where(libres, lam * scn - (1 - lam) * pen, -np.inf)
                    e = int(np.argmax(val)); elegidos.append(e); libres[e] = False
                    maxsim = np.maximum(np.where(np.isinf(maxsim), -1e9, maxsim), simn[e])
                elegidas = cands[elegidos]
            else:
                elegidas = cands[:n]
            rec.append(len(set(elegidas) & set(ocultas)) / min(len(ocultas), n))
            cal.append(float(WR[elegidas].mean()))
            pp = P[elegidas] @ P[elegidas].T
            div.append(float((pp.sum() - len(elegidas)) / (len(elegidas) * (len(elegidas) - 1))))
        res[nombre] = (statistics.mean(rec), statistics.mean(cal), statistics.mean(div))
    prom = statistics.mean(r[0] for r in res.values())
    return prom, res

def linea(etq, prom, res):
    det = " | ".join(f"{k} {100*v[0]:5.1f}" for k, v in res.items())
    cal = statistics.mean(v[1] for v in res.values()); div = statistics.mean(v[2] for v in res.values())
    print(f"{etq:22s} recall@20 {100*prom:5.1f} %  ({det})  WR medio {cal:.2f}  similitud interna {div:.3f}")

print()
print("== 1. Pesos (β = 0, sin MMR) ==")
grilla = [(x / 10, y / 10, round(1 - x / 10 - y / 10, 1)) for x in range(11) for y in range(11 - x)]
resultados = sorted(((*evaluar(w), w) for w in grilla), key=lambda t: -t[0])
for prom, res, w in resultados[:8]:
    linea(f"w = {w}", prom, res)
print("referencias:")
for w in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1/3, 1/3, 1/3)):
    linea(f"w = {tuple(round(x, 2) for x in w)}", *evaluar(w))
maximo = resultados[0][0]
print(f"mejor combinación por peso del plot (umbral: 90 % de {100*maximo:.1f} % = {90*maximo:.1f} %):")
mejor_w = None
for x in sorted({w[0] for w in grilla}):
    prom, res, w = max((t for t in resultados if t[2][0] == x), key=lambda t: t[0])
    linea(f"   plot {x}: w = {w}", prom, res)
    if prom >= 0.9 * maximo:
        mejor_w = w
print(f"pesos elegidos: {mejor_w}")

print()
print(f"== 2. β con w = {mejor_w} (sin MMR) ==")
base_rec = evaluar(mejor_w)[0]
mejor_b = 0.0
for beta in (0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0):
    prom, res = evaluar(mejor_w, beta)
    linea(f"β = {beta}", prom, res)
    if prom >= 0.9 * base_rec:
        mejor_b = beta

LAMBDA = 0.8  # por criterio: MMR aporta poca diversidad medible; queda como protección (6.3)
print()
print(f"== 3. λ de MMR con w = {mejor_w}, β = {mejor_b} ==")
for lam in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
    linea(f"λ = {lam}", *evaluar(mejor_w, mejor_b, lam))
prom, _ = evaluar(mejor_w, mejor_b, LAMBDA)
print()
print(f"RESULTADO: w = {mejor_w}, β = {mejor_b}, λ = {LAMBDA} -> recall@20 {100*prom:.1f} %  "
      f"({time.time()-t_inicio:.0f} s)")
