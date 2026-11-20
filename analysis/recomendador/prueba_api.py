"""Prueba de punta a punta de la API del recommender (docs/recomendador.md, 9.4 y 9.6).

Corre DENTRO del contenedor del backend: llama a http://recommender:8000 por internal-net,
como lo hará el backend, y lee títulos de MongoDB solo para mostrarlos. Usa pymongo y
dcicflix_common, que la imagen del backend ya trae.

1. Espera a que el recommender tenga índice y muestra los 503 de mientras.
2. "Para vos" de un usuario del dataset, similares, rankings, géneros, 404 y 422.
3. Tiempo por petición con 300 usuarios y 300 películas (red + Mongo + cálculo).
4. Usuario nuevo: sin votos, con un 5★ y con tres; usuario con solo un voto bajo.
5. Que el WR tome los votos nuevos en ≤ 60 s.

ESCRIBE EN LA BASE: inserta votos de los usuarios usr_prueba_api* y los borra al terminar,
también si la prueba falla a mitad.

Uso, desde la raíz del repo (en Git Bash, con MSYS_NO_PATHCONV=1 adelante):
    docker compose cp analysis/recomendador/prueba_api.py backend:/tmp/prueba_api.py
    docker compose exec backend python3 /tmp/prueba_api.py
"""
import json, random, statistics, time, urllib.error, urllib.request
from datetime import datetime

from bson import ObjectId
from pymongo import MongoClient

from dcicflix_common.config import MongoSettings

BASE = "http://recommender:8000"
USUARIOS_PRUEBA = ["usr_prueba_api", "usr_prueba_api_bajos"]
settings = MongoSettings.from_env()
db = MongoClient(settings.uri)[settings.db]


def get(path):
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            code, body, headers = r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        code, body, headers = e.code, json.loads(e.read() or b"null"), e.headers
    return code, body, (time.perf_counter() - t) * 1000, headers


def titulo(movie_id):
    doc = db.movies.find_one({"_id": ObjectId(movie_id)}, {"title": 1, "year": 1})
    return f'{doc["title"]} ({doc.get("year")})'


def activa(titulo_, anio):
    return str(db.movies.find_one({"title": titulo_, "year": anio, "deleted": False})["_id"])


def mostrar(items, n, clave="score"):
    for it in items[:n]:
        porque = f'   ← porque te gustó {titulo(it["because"])}' if it.get("because") else ""
        print(f'    {it[clave]:7.3f}  {titulo(it["movie_id"])}{porque}')


def votar(usuario, movie_id, estrellas):
    db.reviews.insert_one({"user_id": usuario, "movie_id": ObjectId(movie_id), "rating": estrellas,
                           "comment": "prueba_api.py", "date": datetime.now(), "deleted": False, "deletedReason": None})


def votos_health():
    return get("/health")[1]["votes"]


print("== 1. Esperando el índice")
inicio, ultimo = time.monotonic(), None
while True:
    try:
        code, body, _, headers = get("/rankings?limit=1")
    except OSError as exc:
        code, body, headers = type(exc).__name__, None, {}
    estado = (code, body.get("phase") if isinstance(body, dict) else None)
    if estado != ultimo:
        print(f"  {time.monotonic() - inicio:5.1f} s  {code}  {json.dumps(body, ensure_ascii=False)[:100]}"
              f"  Retry-After={headers.get('Retry-After')}")
        ultimo = estado
    if code == 200:
        break
    time.sleep(1)

try:
    votos_antes = votos_health()
    godfather = activa("The Godfather", 1972)
    godfather2, goodfellas = activa("The Godfather: Part II", 1974), activa("Goodfellas", 1990)

    print("\n== 2. Usuario del dataset con más votos (los votos del dataset no reflejan gustos, 6.1)")
    usuario = next(db.reviews.aggregate([
        {"$match": {"deleted": False, "rating": {"$in": [1, 2, 3, 4, 5]}}},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 1}]))
    code, body, ms, _ = get(f'/users/{usuario["_id"]}/recommendations?limit=5')
    print(f'  {usuario["_id"]} ({usuario["n"]} votos): {code} source={body["source"]} {ms:.0f} ms')
    mostrar(body["items"], 5)

    print("\n== Similares a The Godfather")
    code, body, ms, _ = get(f"/movies/{godfather}/similar?limit=8")
    print(f"  {code} {ms:.0f} ms")
    mostrar(body["items"], 8)

    print("\n== 404")
    fusionada = db.movies.find_one({"deleted": True}, {"title": 1})
    for etiqueta, path in ((f'copia fusionada ({fusionada["title"]})', f'/movies/{fusionada["_id"]}/similar'),
                           ("ObjectId inventado", f"/movies/{ObjectId()}/similar"),
                           ("género inventado", "/rankings?genre=Inventado")):
        code, body, _, _ = get(path)
        print(f"  {etiqueta}: {code} {body}")

    print("\n== Rankings y géneros")
    code, body, ms, _ = get("/rankings?limit=5")
    print(f"  global: {code} {ms:.0f} ms")
    mostrar(body["items"], 5, clave="wr")
    code, body, _, _ = get("/rankings?genre=Comedy&limit=5")
    print(f"  Comedy: {code}")
    mostrar(body["items"], 5, clave="wr")
    code, body, _, _ = get("/genres")
    print(f"  /genres: {code}, {len(body['items'])} géneros: "
          + ", ".join(f'{g["genre"]} {g["movies"]}' for g in body["items"]))

    print("\n== 422")
    for path in ("/rankings?limit=0", "/rankings?limit=101", "/movies/x/similar?limit=abc"):
        code, body, _, _ = get(path)
        print(f"  {path}: {code} {body['detail'][0]['msg']}")

    print("\n== 3. Tiempo por petición (red + Mongo + cálculo)")
    rng = random.Random(7)
    usuarios = rng.sample(sorted(db.reviews.distinct("user_id", {"deleted": False})), 300)
    peliculas = rng.sample([str(d["_id"]) for d in db.movies.find({"deleted": False}, {"_id": 1})], 300)
    for etiqueta, paths in (("para vos, 300 usuarios", [f"/users/{u}/recommendations" for u in usuarios]),
                            ("similares, 300 películas", [f"/movies/{m}/similar" for m in peliculas])):
        tiempos = sorted(get(p)[2] for p in paths)
        print(f"  {etiqueta}: mediana {statistics.median(tiempos):.1f} ms, p95 {tiempos[int(0.95 * len(tiempos))]:.1f} ms")

    print("\n== 4. Usuario nuevo")
    u = USUARIOS_PRUEBA[0]
    print(f"  sin votos: source={get(f'/users/{u}/recommendations?limit=3')[1]['source']}")
    votar(u, godfather, 5)
    body = get(f"/users/{u}/recommendations?limit=5")[1]
    print(f"  con 5★ a The Godfather, en la petición siguiente: source={body['source']}")
    mostrar(body["items"], 5)
    votar(u, godfather2, 5); votar(u, goodfellas, 5)
    body = get(f"/users/{u}/recommendations?limit=8")[1]
    print(f"  con 5★ también a The Godfather: Part II y Goodfellas: source={body['source']}")
    mostrar(body["items"], 8)

    u = USUARIOS_PRUEBA[1]
    votar(u, godfather, 1)
    body = get(f"/users/{u}/recommendations?limit=100")[1]
    vecinas = {it["movie_id"] for it in get(f"/movies/{godfather}/similar?limit=100")[1]["items"]}
    recibidas = {it["movie_id"] for it in body["items"]}
    print(f"  solo 1★ a The Godfather: source={body['source']}, {len(recibidas)} items; "
          f"The Godfather adentro: {godfather in recibidas}; vecinas adentro: {len(recibidas & vecinas)} de {len(vecinas)}")

    print("\n== 5. El WR toma los votos nuevos en ≤ 60 s")
    t = time.monotonic()
    while votos_health() == votos_antes and time.monotonic() - t < 70:
        time.sleep(2)
    print(f"  /health votes: {votos_antes} → {votos_health()} en {time.monotonic() - t:.0f} s")
finally:
    borrados = db.reviews.delete_many({"user_id": {"$in": USUARIOS_PRUEBA}}).deleted_count
    print(f"\nborrados {borrados} votos de prueba")
