"""Valores de m y M del ranking bayesiano (R4, R5; docs/recomendador.md, 3.4).

En las películas con 2 o más votos propios se esconde la mitad de los votos (semilla 2026), se
calcula WR = (v·R + m·Q5) / (v + m) con la otra mitad y se mide el RMSE al predecir los escondidos,
para una grilla de M (bayesiano de IMDb) y m (votos propios). Q5 sale de una regresión Q -> voto.

Uso: python -I -X utf8 m_y_M.py movies.json.gz reviews.json.gz   (no necesita embeddings)
"""
import gzip, json, sys, collections, statistics, random, math
movs=[json.loads(l) for l in gzip.open(sys.argv[1],'rt',encoding='utf-8')]
def num(x):
    if isinstance(x,str): x=x.replace(',','').strip()
    try: return float(x)
    except: return None
R={};V={}
for d in movs:
    i=d['_id']['$oid']; r=num(d['imdb'].get('rating')); v=num(d['imdb'].get('votes'))
    if r in (14.5,-1): r=None
    if r is not None and r>10: r/=10
    if v is None: r=None
    R[i]=r; V[i]=v
Cimdb=statistics.mean(r for r in R.values() if r is not None)
own=collections.defaultdict(list)
for l in gzip.open(sys.argv[2],'rt',encoding='utf-8'):
    r=json.loads(l); rt=r.get('rating'); u=r.get('user_id'); m=r['movie_id']['$oid']
    if isinstance(rt,str) and rt.isdigit(): rt=int(rt)
    if isinstance(rt,int) and 1<=rt<=5 and u and u!='usr_0000' and m in R: own[m].append(rt)
rng=random.Random(2026)
train={};test={}
for m,v in own.items():
    if len(v)<2: continue
    v=v[:]; rng.shuffle(v); h=len(v)//2
    train[m]=v[h:]; test[m]=v[:h]
C=statistics.mean(x for v in train.values() for x in v)
def fit(M):
    # Q por pelicula y regresion Q -> voto sobre train
    Q={m:(V[m]*R[m]+M*Cimdb)/(V[m]+M) if R[m] is not None else None for m in R}
    xs=[];ys=[]
    for m,v in train.items():
        if Q[m] is None: continue
        for x in v: xs.append(Q[m]); ys.append(x)
    mx=statistics.mean(xs); my=statistics.mean(ys)
    a=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/sum((x-mx)**2 for x in xs); b=my-a*mx
    return Q,a,b
def err(Q,a,b,mm):
    se=n=0
    for m,t in test.items():
        prior=a*Q[m]+b if Q[m] is not None else C
        v=train[m]; wr=(sum(v)+mm*prior)/(len(v)+mm)
        for x in t: se+=(x-wr)**2; n+=1
    return math.sqrt(se/n)
print(f'peliculas con >=2 votos: {len(test)}; votos escondidos: {sum(map(len,test.values()))}')
print('referencias (RMSE, menor es mejor):')
print(f'  promedio global C para todo:            {math.sqrt(statistics.mean((x-C)**2 for t in test.values() for x in t)):.4f}')
print(f'  solo el promedio propio (m=0):           {err(*fit(0),0.0001):.4f}')
Ms=[0,300,1000,3000,10000,30000,100000]; ms=[0,1,2,5,10,20,50,1e9]
print('RMSE por M (filas) y m (columnas):')
print('M\\m     '+''.join(f'{("inf" if x==1e9 else int(x)):>8}' for x in ms))
best=None
for M in Ms:
    Q,a,b=fit(M); row=[]
    for mm in ms:
        e=err(Q,a,b,mm if mm else 0.0001); row.append(e)
        if best is None or e<best[0]: best=(e,M,mm,a,b)
    print(f'{M:<8}'+''.join(f'{e:8.4f}' for e in row))
print('mejor: RMSE %.4f con M=%d, m=%s; mapeo Q5 = %.2f·Q %+.2f'%best)
