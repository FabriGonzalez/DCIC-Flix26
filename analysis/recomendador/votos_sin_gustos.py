"""Prueba de dejar una afuera: ¿los votos del dataset reflejan gustos? (docs/recomendador.md, 6.1)

Para cada usuario se esconde una película que le gustó y se mira si, según cada señal, se parece
más a sus otras películas que le gustaron o a las que no (50 % = azar). Se corre dos veces:
  A. votos tal cual (le gustó = 4-5, no le gustó = 1-2);
  B. votos corregidos por calidad (voto menos lo esperable por su imdb.rating).
Para personas y géneros usa Jaccard, que da el mismo orden de pares que la similitud por conteo.

Uso: python -I -X utf8 votos_sin_gustos.py movies.json.gz reviews.json.gz cache/plots.npy
"""
import gzip, json, sys, re, collections, statistics
import numpy as np
movs=[json.loads(l) for l in gzip.open(sys.argv[1],'rt',encoding='utf-8')]
V=np.load(sys.argv[3]); V/=np.linalg.norm(V,axis=1,keepdims=True)
pos={d['_id']['$oid']:i for i,d in enumerate(movs)}; imdb=[d['imdb']['id'] for d in movs]
def ir(d):
    r=d['imdb'].get('rating')
    try: r=float(r)
    except: return None
    if r in (14.5,-1): return None
    return r/10 if r>10 else r
I=[ir(d) for d in movs]
def gen(d):
    g=d.get('genres')
    if isinstance(g,str): g=re.split(r' / |\||, ',g)
    return {x.strip() for x in g} if g else set()
G=[gen(d) for d in movs]
P=[{re.sub(r'\s*\(.*$','',x).strip() for f in ('directors','cast','writers') for x in (d.get(f) or [])} for d in movs]
U=collections.defaultdict(list); xs=[]; ys=[]
for l in gzip.open(sys.argv[2],'rt',encoding='utf-8'):
    r=json.loads(l); rt=r.get('rating'); u=r.get('user_id'); m=r['movie_id']['$oid']
    if isinstance(rt,str) and rt.isdigit(): rt=int(rt)
    if not isinstance(rt,int) or not 1<=rt<=5 or not u or u=='usr_0000' or m not in pos or I[pos[m]] is None: continue
    U[u].append((pos[m],rt)); xs.append(I[pos[m]]); ys.append(rt)
a,b=np.polyfit(xs,ys,1); print(f'ajuste: voto ≈ {a:.2f}·imdb {b:+.2f}')
jac=lambda p,q: len(p&q)/len(p|q) if p|q else 0
sims={'imdb (calidad)':lambda p,q:-abs(I[p]-I[q]),'plot':lambda p,q: float(V[p]@V[q]),'generos':lambda p,q: jac(G[p],G[q]),'personas':lambda p,q: jac(P[p],P[q])}
def prueba(etiqueta):
    print(etiqueta)
    for n,f in sims.items():
        gana=tot=0
        for v in U.values():
            if etiqueta.startswith('A'):
                bu=[i for i,r in v if r>=4]; ma=[i for i,r in v if r<=2]
            else:
                res=sorted(v,key=lambda t:t[1]-(a*I[t[0]]+b)); k=max(2,len(v)//4)
                ma=[i for i,_ in res[:k]]; bu=[i for i,_ in res[-k:]]
            if len(bu)<3 or len(ma)<2: continue
            for h in bu:
                ob=[i for i in bu if i!=h and imdb[i]!=imdb[h]]; om=[i for i in ma if imdb[i]!=imdb[h]]
                if not ob or not om: continue
                sb=statistics.mean(f(h,i) for i in ob); sm=statistics.mean(f(h,i) for i in om)
                if sb==sm: continue
                gana+=sb>sm; tot+=1
        print(f'   {n:15s}: {100*gana/tot:.1f}% de {tot}')
prueba('A. buenas = 4-5 estrellas, malas = 1-2')
prueba('B. corregido por calidad: buenas/malas = cuarto superior/inferior de (voto - lo esperable por imdb)')
