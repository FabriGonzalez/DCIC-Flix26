# Esqueleto de contenedores

> **Estado: plan final, aprobado el 2026-11-16.** F1 implementada. Próximo paso: F2. El porqué de cada elección está en el [registro de decisiones](#registro-de-decisiones); el cómo, en [Diseño](#diseño); el orden de trabajo, en [Fases de implementación](#fases-de-implementación).

## Objetivo

Levantar con `docker compose up --build` la arquitectura de contenedores descrita en el [README](../README.md), **sin funcionalidad de negocio**, con todos los servicios conectados y sanos. La base tiene que permitir verificar automáticamente, a medida que crezca el sistema, que la arquitectura se sigue cumpliendo.

### Alcance

| Entra | Queda afuera |
| :-- | :-- |
| `docker-compose.yml` con todos los servicios | Catálogo, votos y reseñas reales |
| Las 3 redes y el único puerto publicado | Lógica de limpieza y llamadas al LLM |
| Dockerfile por servicio propio | Algoritmo del recomendador |
| Healthchecks, `depends_on` y reinicio | UI real (alcanza con una pantalla que muestre `/api/health`) |
| Volúmenes de MongoDB y RabbitMQ | `GET /status`, `/audit`, traducción, chat |
| Carga del dataset real, en crudo | Publicar o consumir mensajes (los stubs solo verifican la topología) |
| `.env.example` | |
| Verificaciones automáticas de la arquitectura | |
| Modo desarrollo del `frontend` (perfil `dev`) | |

### Criterio de "funcionando"

1. `docker compose up --build` en un clon limpio, sin pasos manuales, deja todos los servicios en *healthy* (y `topology-init` en `Exited (0)`).
2. `http://localhost:8080` sirve el `frontend`, y `/api/health` llega al `backend` a través de él.
3. Solo el `frontend` tiene un puerto publicado en el host (en modo normal).
4. Aislamiento: el `frontend` no resuelve `mongodb`, `rabbitmq` ni `recommender`. Los servicios que están solo en `internal-net` no salen a internet. `backend` y `cleaning-agent` sí salen.
5. Cada servicio alcanza sus dependencias según la tabla de comunicación del README, y la topología de RabbitMQ existe y es la de `topology.py`.
6. Un `down` seguido de un nuevo `up` vuelve a dejar todo sano, y los datos de Mongo persisten en el volumen.

## Registro de decisiones

| # | Decisión | Elegido | Descartado | Motivo |
| :-- | :-- | :-- | :-- | :-- |
| D1 | Nivel del stub | **Conectado:** se conecta a sus dependencias y solo reporta *healthy* si las críticas responden | Vivo (no prueba la arquitectura); de punta a punta (ya es funcionalidad) | Prueba cada línea de la tabla de comunicación sin lógica de negocio. |
| D2 | Lenguaje del lado servidor | **Python** para `backend`, `recommender`, `ingest-consumer`, `cleaning-agent` (y `topology-init`) | Mixto Node + Python; todo Node | El recomendador y el agente necesitan el ecosistema de datos de Python; un solo lenguaje permite un helper compartido. |
| D3 | Frontend | **React + TypeScript (Vite)**; build servido por **nginx**, que reenvía `/api` | Página estática sola; JS | Elegido por el usuario. Dockerfile de dos etapas (node build → nginx). |
| D4 | Compartir el helper Python | **Contexto de build en la raíz** (`context: .`, `dockerfile: services/<svc>/Dockerfile`) + `.dockerignore` | `additional_contexts` (depende de la versión de Compose); copia por servicio; imagen base propia (rompe el `up` sin pasos manuales) | Funciona en cualquier instalación del grupo. |
| D5 | Modo desarrollo del `frontend` | Servicio `frontend-dev` con perfil `dev`: Vite con recarga en caliente, código montado, `usePolling` (Windows), proxy `/api` → `backend:8000`, puerto 5173 | Solo el build de producción | Elegido por el usuario. Es poco código y no toca la base; va como última fase. |
| D6 | Puertos | `frontend` 80 → host `${FRONTEND_PORT:-8080}`; `backend` y `recommender` 8000 internos; Mongo 27017 y Rabbit 5672 | Puertos distintos por servicio Python | Sin conflicto porque no se publican; Dockerfiles y healthchecks uniformes. |
| D7 | Datos en Mongo | **Dataset real** con el [mongo-init.sh](../dataset/mongo-init.sh) provisto, sin modificar, montando `./dataset` en `/docker-entrypoint-initdb.d`; carga en crudo | Muestra mínima; base vacía; script propio | Elegido por el usuario. La limpieza es del `cleaning-agent`, que necesita ver la suciedad. |
| D8 | Infraestructura | `mongo:8.0` y `rabbitmq:4.1` fijadas; usuario propio en ambos; Rabbit con `hostname` fijo y volumen; sin panel de Rabbit; `.gitattributes` con LF para `*.sh` | Tags `latest`; `guest/guest`; imagen `-management` | Cada punto evita una falla concreta del criterio de "funcionando". |
| D9 | Estilo de I/O del helper | **Mixto:** `aio/` (`aio-pika` + `AsyncMongoClient`) para `backend` y `recommender`; `sync/` (`pika` + `MongoClient`) para `ingest-consumer`, `cleaning-agent` y `topology-init`. `config`, `logging`, `health` y `topology` compartidos | Un helper async para todos; todo sync | Elegido por el usuario: cada servicio en su estilo natural. **Nombres y argumentos de la topología solo en `topology.py`**; las variantes `sync/` y `aio/` son traductores genéricos sin nombres propios. |
| D10 | Quién administra la topología de Rabbit | **Contenedor `topology-init`**: declara todo y termina; los servicios verifican en forma pasiva (`passive=True`) | Todos declaran todo; cada uno declara lo suyo; `definitions.json` del broker (choca con los secretos en `.env`); el `backend` como dueño (acopla a los workers) | Elegido por el usuario. Un único responsable, sin carrera en el fanout. |
| D11 | Topología | Cola `interactions` (durable, `x-dead-letter-exchange: interactions.dlx`) → exchange fanout `interactions.dlx` → cola `interactions.errors`; exchange fanout `data.cleaned` → cola `recommender.data-cleaned`; todo durable | Cola simple para `data.cleaned` | Cumple el README (durable, cola de errores) y deja `data.cleaned` abierto a más suscriptores. |
| D12 | Health | `/health` → 200 o 503 con un JSON común; dependencias **críticas** (Mongo, Rabbit, topología verificada) frente a **informativas** (`recommender` para el `backend`, `backend` para el `frontend`); healthcheck con Python, no `curl`; el LLM fuera del health | Health que dependa de todas las conexiones por igual | El catálogo tiene que seguir navegable aunque el recomendador no esté listo; una API externa caída no tira servicios propios. |
| D13 | Health de los workers sin HTTP | **Archivo de latido** `/tmp/health.json`: un hilo `daemon` del helper `sync/` cada 10 s; válido por 30 s; el healthcheck es `python -m dcicflix_common.sync.healthcheck` | Chequeo con conexiones nuevas; mini servidor HTTP | Mide las conexiones reales del proceso, no abre puertos y no da falsos *unhealthy* mientras el `cleaning-agent` trabaja. |
| D14 | *Unhealthy* que no se reinicia | **Reconectar lo recuperable, morir ante lo irrecuperable:** el helper reintenta ante errores de conexión; ante un canal cerrado por protocolo o una topología que deja de verificarse, el proceso termina con código 1 y `unless-stopped` lo levanta | Watchdog por tiempo (reinicios inútiles con Mongo caído); contenedor `autoheal` (necesita `docker.sock`) | Elegido por el usuario. Usa lo que ya tiene Compose, sin componentes extra. Límite aceptado: un deadlock queda *unhealthy* sin reinicio. |
| D15 | Configuración sin pasos manuales | **Valores de desarrollo por defecto en el compose** (`${VAR:-valor}`); `.env` opcional que los sobrescribe; `LLM_API_KEY` vacía por defecto | `.env` obligatorio (cambia el criterio 1); `.env` commiteado (riesgo de commitear la key real) | Elegido por el usuario. Cumple el criterio 1 y la key real nunca va a Git. Las contraseñas por defecto no exponen nada: Mongo y Rabbit solo están en `internal-net`. |
| D16 | Dónde corren las verificaciones | **pytest en el host** que maneja la CLI de `docker compose` con `subprocess` (sin SDK de Docker); tests estáticos y dinámicos separados por marcas | Contenedor de tests (necesita `docker.sock` y no ve el puerto del host); script bash o PowerShell (depende del shell, comparaciones frágiles) | Elegido por el usuario. Prueba los 6 criterios desde donde se observan y corre igual en Windows, Linux y CI. |

## Diseño

### Servicios

| Servicio | Estilo | Redes | Se conecta a | Expone | Críticas | Informativas |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| `frontend` | nginx + React/TS | `public-net` | `backend` (proxy `/api`) | `:80` → host 8080 | nginx responde | `backend` |
| `frontend-dev` (perfil `dev`) | Vite | `public-net` | `backend` | `:5173` → host 5173 | — | — |
| `backend` | async, FastAPI | `public-net`, `internal-net` | `mongodb`, `rabbitmq`, `recommender` | `:8000` `/health` | Mongo, Rabbit, topología | `recommender` |
| `recommender` | async, FastAPI | `internal-net` | `mongodb`, `rabbitmq` | `:8000` `/health` | Mongo, Rabbit, topología | — |
| `ingest-consumer` | sync | `internal-net` | `mongodb`, `rabbitmq` | — (latido) | Mongo, Rabbit, topología | — |
| `cleaning-agent` | sync | `internal-net`, `egress-net` | `mongodb`, `rabbitmq` | — (latido) | Mongo, Rabbit, topología | — |
| `topology-init` | sync, una vez | `internal-net` | `rabbitmq` | — | termina con código 0 | — |
| `mongodb` | `mongo:8.0` | `internal-net` | — | 27017 | `mongosh --host mongodb` ping (por la red, no `localhost`) | — |
| `rabbitmq` | `rabbitmq:4.1` | `internal-net` | — | 5672 | conexión TCP a 5672 | — |

- **Todos los servicios declaran `networks:` explícitamente.** Si no, Docker los conecta a una red `default` fuera del diseño.
- `internal-net` lleva `internal: true`.
- nginx saca el prefijo `/api`: el `backend` expone `/health`, no `/api/health`.

### Estructura del repo

```
DCIC-Flix26/
├── docker-compose.yml
├── .env.example
├── .dockerignore          excluye node_modules, dataset/, .git
├── .gitattributes         *.sh text eol=lf · *.gz binary
├── .gitignore             .env · dataset/*.json (restos de una carga fallida)
├── README.md
├── docs/
│   └── esqueleto-contenedores.md
├── dataset/               mongo-init.sh, movies.json.gz, reviews.json.gz (13 MB, va en Git)
├── libs/
│   └── common/
│       ├── pyproject.toml          extras [sync] (pika, pymongo) y [async] (aio-pika, pymongo)
│       └── dcicflix_common/
│           ├── config.py           variables de entorno; falla al arrancar si falta una obligatoria
│           ├── logging.py
│           ├── health.py           forma común del JSON de health
│           ├── topology.py         SOLO DATOS: exchanges, colas, bindings, constantes
│           ├── sync/
│           │   ├── mongo.py        MongoClient con reintentos
│           │   ├── rabbit.py       pika con reconexión + declare_topology() / verify_topology()
│           │   ├── heartbeat.py    hilo de latido → /tmp/health.json
│           │   └── healthcheck.py  lo ejecuta Docker
│           └── aio/
│               ├── mongo.py        AsyncMongoClient con reintentos
│               └── rabbit.py       aio-pika connect_robust + verify_topology()
├── services/
│   ├── frontend/          Dockerfile (2 etapas), nginx.conf, package.json, vite.config.ts, src/
│   ├── backend/           Dockerfile, requirements.txt, app/
│   ├── recommender/
│   ├── ingest-consumer/
│   ├── cleaning-agent/
│   └── topology-init/     Dockerfile, main.py
└── tests/
    ├── requirements.txt   pytest (y el helper, para importar topology.py)
    └── architecture/      tests static, dynamic y slow; matriz REACHABILITY
```

Ejemplo de Dockerfile Python (contexto en la raíz):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY libs/common /libs/common
RUN pip install "/libs/common[async]"
COPY services/backend/requirements.txt .
RUN pip install -r requirements.txt
COPY services/backend/app ./app
```

### Infraestructura

**`mongodb`**
- `MONGO_INITDB_ROOT_USERNAME` y `MONGO_INITDB_ROOT_PASSWORD` desde `MONGO_USER` y `MONGO_PASSWORD`, con valores por defecto (D15). Base `peliculas-proyectos`, que los servicios leen de `MONGO_DB`.
- Volúmenes: `mongo-data:/data/db` y `./dataset:/docker-entrypoint-initdb.d`. Va **sin `:ro`**, porque el script descomprime ahí.
- Durante la carga, el servidor temporal corre sin autenticación y solo en `127.0.0.1` (verificado en el entrypoint oficial), así que `mongoimport` sin credenciales funciona.
- La carga corre **solo con el volumen vacío**. Para recargar, o después de una carga fallida: `docker compose down -v`.
- **El healthcheck se conecta con `--host mongodb`, no a `localhost`.** Medido en F1: durante la carga, el ping a `localhost` ya responde (a los 17 s, cuando la carga terminó a los 37 s); el ping por la red solo responde con el servidor definitivo (45 s). Así, *healthy* significa dataset cargado.
- Resultado de la carga: 19.842 películas y 61.488 reseñas, con los índices de `mongo-init.sh`.

**`rabbitmq`**
- Usuario propio (`RABBITMQ_DEFAULT_USER` y `RABBITMQ_DEFAULT_PASS`, desde `RABBITMQ_USER` y `RABBITMQ_PASSWORD`), porque `guest` solo se conecta desde dentro del contenedor.
- `hostname: rabbitmq`, fijo para que persistan los datos.
- Volumen `rabbitmq-data:/var/lib/rabbitmq`.
- Sin panel web. Las colas se ven con `docker compose exec rabbitmq rabbitmqctl list_queues`.
- **El healthcheck es una conexión TCP al 5672** (`bash -c 'exec 3<>/dev/tcp/127.0.0.1/5672'`), la prueba que recomienda la [documentación de RabbitMQ](https://www.rabbitmq.com/docs/monitoring#health-checks). `rabbitmq-diagnostics ping` solo verifica que corra Erlang: medido en F1, respondía a los 7 s y el puerto AMQP recién aceptaba conexiones a los 27 s. Además, cada comando `rabbitmq-diagnostics` tiene un costo de CPU.

### Health

```json
{
  "service": "backend",
  "status": "ok",
  "dependencies": { "mongodb": "ok", "rabbitmq": "ok" },
  "info":         { "recommender": "ok" }
}
```

- Servicios HTTP: `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"`. La imagen slim no trae `curl`.
- Workers: el mismo JSON en `/tmp/health.json`, más la hora.
- Más adelante, el `recommender` agrega `"ready": true/false`.

### Arranque y resiliencia

```
mongodb  ──healthy───────────────────────────────┐
                                                 ├──▶ backend, recommender,
rabbitmq ──healthy──▶ topology-init ──exit 0─────┘    ingest-consumer, cleaning-agent
frontend: sin depends_on
```

- **`depends_on` es comodidad del arranque; los reintentos del helper son la garantía.**
- nginx resuelve `backend` **en cada pedido**: `resolver 127.0.0.11 valid=10s;` + `set $backend http://backend:8000;` + `rewrite ^/api/(.*)$ /$1 break;`. Si no, no arranca sin el `backend` o queda con una IP vieja tras un reinicio.

| Servicio | `restart` | `interval` | `retries` | `start_period` |
| :-- | :-- | :-- | :-- | :-- |
| `mongodb` | `unless-stopped` | 5 s | 10 | 120 s (la carga tardó ~40 s y el *healthy* llegó a los ~57 s; margen para máquinas lentas) |
| `rabbitmq` | `unless-stopped` | 5 s | 10 | 20 s |
| `topology-init` | `"no"` | — | — | — |
| `backend`, `recommender` | `unless-stopped` | 10 s | 3 | 15 s |
| `ingest-consumer`, `cleaning-agent` | `unless-stopped` | 10 s | 3 | 15 s |
| `frontend` | `unless-stopped` | 10 s | 3 | 5 s |

- `topology-init` no se reinicia: reintenta la conexión por sí mismo, y si falla igual es un error real (por ejemplo `PRECONDITION_FAILED`), que tiene que verse.
- `topology-init` en `Exited (0)` es lo esperado. Hay que documentarlo en el README.
- **Política ante fallas (D14):** Compose reinicia cuando el proceso termina, no cuando falla el healthcheck. Por eso el helper distingue errores: ante uno de conexión, reintenta; ante uno irrecuperable, termina con código 1 para que `unless-stopped` actúe.

### Configuración (D15)

- Cada servicio recibe **solo sus variables** por `environment:`, con anclas YAML (`x-mongo-env`, `x-rabbit-env`). Sin `env_file` común: la key del LLM llega solo a `backend` y `cleaning-agent`.
- `config.py` arma la URI de Mongo con `authSource=admin` y la contraseña escapada con `quote_plus`.
- `MONGO_DB=peliculas-proyectos` fijo en el compose, fuera de `.env`: el `mongo-init.sh` lo tiene escrito en el código.
- `LLM_API_KEY` es opcional en `config.py`; el resto de las variables son obligatorias.
- Mongo y Rabbit crean el usuario solo con el volumen vacío: cambiar credenciales exige `docker compose down -v`. Se documenta en `.env.example`.
- Variables: `FRONTEND_PORT`, `MONGO_USER`, `MONGO_PASSWORD`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `LLM_API_KEY`, `LOG_LEVEL`.

### Verificación de la arquitectura (D16)

`tests/architecture/`, con pytest en el host (Python 3.12 + `pip install -r tests/requirements.txt`). Llama a `docker compose` con `subprocess`.

| Marca | Necesita `up` | Verifica |
| :-- | :-- | :-- |
| `static` | No: lee `docker compose config --format json` | Solo el `frontend` publica puertos; todos declaran `networks:` y no existe `default`; `internal-net` es `internal: true`; tags fijos; `restart` según la tabla de arranque |
| `dynamic` | Sí | Todos *healthy* y `topology-init` en `Exited (0)`; `localhost:8080/api/health` → 200; matriz de alcance y aislamiento; topología del broker igual a `topology.py` |
| `slow` | Sí | Persistencia: cantidad de documentos igual tras `down` + `up` |

- Lo esperado vive en `tests/architecture/spec.py` (redes, redes internas, servicios con puerto, servicios de una sola vez, política de reinicio); los tests solo comparan.
- Uso: `python -m venv .venv`, `pip install -r tests/requirements.txt`, `docker compose up -d --wait` y `pytest` (o `pytest -m static`).
- `compose config` omite las redes que ningún servicio usa: el test de redes compara por inclusión, y la existencia de cada conexión la prueba la matriz.
- **La tabla de comunicación es datos del test:** una matriz `REACHABILITY` (qué resuelve cada servicio, qué no, y si sale a internet) genera los tests de alcance y aislamiento. Cambiar la arquitectura obliga a cambiar esa tabla.
- La topología se compara importando `dcicflix_common.topology` contra `rabbitmqctl list_queues` y `list_exchanges`.
- Los tests de salida a internet se saltean con aviso si la máquina no tiene conexión.
- Cada fase agrega los tests de lo que construye.

## Fases de implementación

Cada fase es un commit (o pocos), termina con `docker compose up --build` sano y suma sus tests. Ninguna depende de una posterior.

| Fase | Qué se construye | Se verifica con |
| :-- | :-- | :-- |
| **F1. Base e infraestructura** | `.gitattributes` (antes de commitear `dataset/`), `.gitignore`, `.dockerignore`, `.env.example`; commit de `dataset/` y `docs/`; `docker-compose.yml` con `mongodb`, `rabbitmq`, las 3 redes y los volúmenes; esqueleto de `tests/architecture/` con los tests `static` | Mongo y Rabbit *healthy*; `movies` y `reviews` cargadas; `pytest -m static` en verde |
| **F2. Helper común y topología** | `libs/common`: `config`, `logging`, `health`, `topology`, `sync/`; servicio `topology-init`; cambios en el README | `topology-init` en `Exited (0)`; test de topología |
| **F3. Workers** | `ingest-consumer` y `cleaning-agent` con latido y la política de D14 | *healthy* por latido; matriz de alcance para ambos; salida a internet solo del `cleaning-agent` |
| **F4. Servicios HTTP** | Helper `aio/`; `backend` y `recommender` con `/health` | *healthy*; el `backend` informa al `recommender` en `info`; matriz para ambos |
| **F5. Frontend** | React + TS (Vite) con una pantalla que muestra `/api/health`; Dockerfile de 2 etapas; `nginx.conf` con el resolver por pedido | `localhost:8080` y `/api/health` → 200; aislamiento del `frontend`; criterios 1 a 5 completos |
| **F6. Resiliencia y persistencia** | Test `slow` de persistencia; prueba de reconexión (parar y volver a levantar `rabbitmq` y `mongodb`) | Criterio 6; los servicios vuelven a *healthy* sin intervención |
| **F7. Modo desarrollo** | `frontend-dev` con perfil `dev` (D5) | `docker compose --profile dev up`: recarga en caliente en `localhost:5173` |
| F8. CI (opcional) | GitHub Actions que corre `static` en cada push y `dynamic` en los PR | El workflow en verde |

Por qué este orden:

- **Infraestructura y tests estáticos primero:** desde el primer commit, un puerto de más o un servicio sin `networks:` hace fallar un test.
- **`sync/` antes que `aio/`:** lo usa `topology-init`, que es requisito de todos los demás servicios.
- **Workers antes que el `backend`:** prueban latido y topología sin sumar FastAPI al mismo tiempo, así una falla queda localizada en una capa.
- **`frontend` al final del camino principal:** es lo único que depende del `backend` y cierra los criterios 2 a 4.
- **F6 a F8 no bloquean nada:** prueban lo existente o agregan comodidad.

## Pendientes

- Acceso al panel de RabbitMQ en el perfil `dev`, si después hace falta.
- **Consultar a la cátedra cómo obtiene la API key del LLM** (su propia key, una key del grupo con límite de gasto y revocable, o un modelo local). Ocultar la key dentro del proyecto no es posible: quien ejecuta `docker compose` la puede leer.
- **Sin API key, la app tiene que funcionar:** traducción y chat responden "no disponible", y el `cleaning-agent` saltea lo que requiere el LLM sin caerse.
- Observación para el `cleaning-agent`: `rating` trae `null`, texto (`"4"`) y valores fuera de rango (`10`, `-1`, `100`, `999`).

### Cambios a hacer en el README (fase F2)

- Agregar `topology-init` a la tabla de servicios.
- Reemplazar "cada servicio declara al iniciar las colas que usa" por "`topology-init` declara la topología; los servicios la verifican".
- Aclarar que `topology-init` en `Exited (0)` es normal.
- Agregar cómo correr los tests de arquitectura (`pip install -r tests/requirements.txt` y `pytest -m static` / `-m dynamic`), y que la API key del LLM es opcional y va en `.env`.
