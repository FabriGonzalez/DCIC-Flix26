"""Cálculo por petición (R15; docs/recomendador.md, 7.1).

Compara el costo de "Recomendadas para vos" calculando contra todo el catálogo (A) con el de leer
vecinos precalculados (B), con 300 usuarios reales del dataset, y cuánto coinciden sus top 10.
Usa pesos anteriores a la calibración (0,5 · 0,2 · 0,3) y sin β: solo sirve para tiempos y
coincidencia entre métodos, no para la calidad de las recomendaciones.

Uso: python -I -X utf8 vecinos_precalculados.py movies.json.gz reviews.json.gz cache/plots.npy
"""
import gzip, json, math, re, statistics, sys, time, collections, random

import numpy as np
from scipy import sparse

movies_gz, reviews_gz, vec_path = sys.argv[1:4]
movs = [json.loads(l) for l in gzip.open(movies_gz, "rt", encoding="utf-8")]
N = len(movs)
pos = {d["_id"]["$oid"]: i for i, d in enumerate(movs)}

# --- Matrices de las tres señales (cada fila normalizada) ---
P = np.load(vec_path).astype(np.float32)
P /= np.linalg.norm(P, axis=1, keepdims=True)

def generos(d):
    g = d.get("genres")
    if isinstance(g, str):
        g = re.split(r" / |\||, ", g)
    return {x.strip() for x in g} if g else set()
Gs = [generos(d) for d in movs]
gidx = {g: j for j, g in enumerate(sorted({g for s in Gs for g in s}))}
G = np.zeros((N, len(gidx)), np.float32)
for i, s in enumerate(Gs):
    for g in s:
        G[i, gidx[g]] = 1
G /= np.maximum(np.linalg.norm(G, axis=1, keepdims=True), 1e-9)

Ps = [{re.sub(r"\s*\(.*$", "", x).strip() for f in ("directors", "cast", "writers") for x in (d.get(f) or [])} for d in movs]
df = collections.Counter(n for s in Ps for n in s)
pidx = {n: j for j, n in enumerate(n for n, c in df.items() if c >= 2)}
rows, cols, vals = [], [], []
for i, s in enumerate(Ps):
    for n in s:
        if n in pidx:
            rows.append(i); cols.append(pidx[n]); vals.append(math.log(N / df[n]))
T = sparse.csr_matrix((vals, (rows, cols)), shape=(N, len(pidx)), dtype=np.float32)
norms = np.sqrt(np.asarray(T.multiply(T).sum(axis=1)).ravel())
T = sparse.diags(1 / np.maximum(norms, 1e-9)).dot(T).tocsr()

WR = np.random.default_rng(0).uniform(3, 4.5, N).astype(np.float32)  # solo para medir tiempos
w1, w2, w3, beta = 0.5, 0.2, 0.3, 0.0
print(f"matrices: plot {P.shape} {P.nbytes/1e6:.0f} MB | géneros {G.shape} | personas {T.shape} "
      f"{(T.data.nbytes + T.indices.nbytes + T.indptr.nbytes)/1e6:.0f} MB (dispersa)")

# --- Usuarios reales del dataset, para tener perfiles de tamaño realista ---
U = collections.defaultdict(list)
for l in gzip.open(reviews_gz, "rt", encoding="utf-8"):
    r = json.loads(l); rt = r.get("rating"); m = r["movie_id"]["$oid"]
    if isinstance(rt, str) and rt.isdigit():
        rt = int(rt)
    if isinstance(rt, int) and 1 <= rt <= 5 and r.get("user_id") and m in pos:
        U[r["user_id"]].append((pos[m], rt))
usuarios = random.Random(2026).sample(list(U.values()), 300)

def cos(M, v):
    n = np.linalg.norm(v) if not sparse.issparse(v) else math.sqrt(v.multiply(v).sum())
    if n == 0:
        return np.zeros(M.shape[0], np.float32)
    s = M @ (v.T if sparse.issparse(v) else v)
    return (s.toarray().ravel() if sparse.issparse(s) else np.asarray(s).ravel()) / n

def mmr(cands, scores, k=10, lam=0.7):
    elegidos = []
    sim = P[cands] @ P[cands].T
    restantes = list(range(len(cands)))
    while restantes and len(elegidos) < k:
        mejor = max(restantes, key=lambda r: lam * scores[r] - (1 - lam) * (max(sim[r, e] for e in elegidos) if elegidos else 0))
        elegidos.append(mejor); restantes.remove(mejor)
    return [cands[e] for e in elegidos]

def recomendar_catalogo(votos):
    idx = np.array([i for i, _ in votos]); r = np.array([x for _, x in votos], np.float32)
    medio = (r.sum() + 5 * 3.525) / (len(r) + 5)
    pw = r - medio
    pp = pw @ P[idx]; gp = pw @ G[idx]; tp = sparse.csr_matrix(pw) @ T[idx]
    score = w1 * cos(P, pp) + w2 * cos(G, gp) + w3 * cos(T, tp) + beta * WR
    score[idx] = -np.inf
    top = np.argpartition(-score, 200)[:200]
    return mmr(list(top), score[top])

def medir(f, args, nombre):
    f(args[0])  # calentamiento
    t = []
    for a in args:
        t0 = time.perf_counter(); f(a); t.append((time.perf_counter() - t0) * 1000)
    t.sort()
    print(f"{nombre}: mediana {statistics.median(t):.1f} ms | p95 {t[int(.95*len(t))]:.1f} ms | máx {t[-1]:.1f} ms")

print(f"votos por usuario en la muestra: mediana {statistics.median(len(v) for v in usuarios)}")
medir(recomendar_catalogo, usuarios, "A. producto contra todo el catálogo (+ MMR)")
medir(lambda i: recomendar_catalogo([(i, 5)]), random.Random(1).sample(range(N), 300), "A. 'similares' (una película)")


# --- Comparación A vs B según K y cantidad de votos ---
Tt = T.T.tocsr()
def precalcular(K):
    t0=time.perf_counter(); ids=np.zeros((N,K),np.int32); ss=np.zeros((N,K),np.float32)
    for a in range(0,N,1000):
        b=min(a+1000,N)
        S=w1*(P[a:b]@P.T)+w2*(G[a:b]@G.T)+w3*(T[a:b]@Tt).toarray()
        S[np.arange(b-a),np.arange(a,b)]=-np.inf
        top=np.argpartition(-S,K,axis=1)[:,:K]; ids[a:b]=top; ss[a:b]=np.take_along_axis(S,top,axis=1)
    return ids,ss,time.perf_counter()-t0
def top_A(votos,k=10):
    idx=np.array([i for i,_ in votos]); r=np.array([x for _,x in votos],np.float32)
    pw=r-(r.sum()+5*3.525)/(len(r)+5)
    if not pw.any(): pw=r-3.525
    pp=pw@P[idx]; gp=pw@G[idx]; tp=sparse.csr_matrix(pw)@T[idx]
    s=w1*(P@pp)+w2*(G@gp)+w3*np.asarray((T@tp.T).todense()).ravel(); s[idx]=-np.inf
    s=np.where(s>0,s,-np.inf)
    return set(j for j in np.argsort(-s)[:k] if s[j]>-np.inf)
def top_B(votos,ids,ss,k=10):
    r=np.array([x for _,x in votos],np.float32); medio=(r.sum()+5*3.525)/(len(r)+5)
    if not (r-medio).any(): medio=3.525
    acc=collections.defaultdict(float); vistos={i for i,_ in votos}
    for i,x in votos:
        for j,s in zip(ids[i],ss[i]):
            if j not in vistos: acc[j]+=(x-medio)*s
    pos_=[j for j in acc if acc[j]>0]
    return set(sorted(pos_,key=lambda j:-(acc[j]+beta*WR[j]))[:k]), len(pos_)
rng=random.Random(7)
grupos={n:[rng.sample(v,n) for v in usuarios if len(v)>=n] for n in (1,3,5)}
grupos['todos']=usuarios
for K in (50,100,200):
    ids,ss,t=precalcular(K)
    print(f'K={K}: precálculo {t:.1f} s, {(ids.nbytes+ss.nbytes)/1e6:.0f} MB')
    for g,us in grupos.items():
        sol=[];cand=[];cortos=0
        for v in us:
            r=[x for _,x in v]; medio=(sum(r)+5*3.525)/(len(r)+5)
            if all(x<=medio for x in r): cortos+=1; continue
            b,nc=top_B(v,ids,ss); a=top_A(v); sol.append(len(a&b)/max(len(a),1)); cand.append(nc)
        print(f'   votos {g!s:>5}: coincidencia top10 A/B {100*statistics.mean(sol):5.1f} %  candidatas positivas mediana {statistics.median(cand):6.0f}  solo votos negativos {cortos}/{len(us)}')
