# Esqueleto de contenedores

> **Estado: plan final, aprobado el 2026-11-16.** F1 a F7 implementadas: los criterios 1 a 5 se cumplen (comprobado en un clon limpio), el 6 lo prueban los tests `slow`, y el modo desarrollo funciona con `--profile dev`. Queda F8 (CI, opcional). El porqué de cada elección está en el [registro de decisiones](#registro-de-decisiones); el cómo, en [Diseño](#diseño); el orden de trabajo, en [Fases de implementación](#fases-de-implementación).

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
│       ├── pyproject.toml          extras [sync] (pika, pymongo) y [async] (aio-pika, pymongo), versiones fijas
│       ├── tests/                  tests unitarios: config y coherencia de topology.py
│       └── dcicflix_common/
│           ├── config.py           variables de entorno; falla al arrancar si falta una obligatoria
│           ├── logging.py
│           ├── health.py           forma común del JSON de health
│           ├── topology.py         SOLO DATOS: exchanges, colas, bindings, constantes
│           ├── errors.py           TopologyError, común a sync/ y aio/
│           ├── sync/
│           │   ├── mongo.py        MongoClient con reintentos
│           │   ├── rabbit.py       pika con reconexión + declare_topology() / verify_topology()
│           │   ├── heartbeat.py    hilo de latido → /tmp/health.json
│           │   ├── healthcheck.py  lo ejecuta Docker
│           │   └── worker.py       bucle común de los workers (stub conectado, D1 y D14)
│           └── aio/
│               ├── mongo.py        AsyncMongoClient con reintentos
│               ├── rabbit.py       aio-pika connect_robust + verify_topology()
│               ├── monitor.py      chequeo cada 10 s y la "foto" que devuelve /health (sin dependencias)
│               └── service.py      conexiones + monitor de backend y recommender (sin framework web)
├── services/
│   ├── frontend/          Dockerfile (build → nginx, más la etapa dev de F7), nginx.conf, package.json, vite.config.ts, src/
│   ├── backend/           Dockerfile, requirements.txt, app/
│   ├── recommender/
│   ├── ingest-consumer/
│   ├── cleaning-agent/
│   └── topology-init/     Dockerfile, main.py
├── pytest.ini             pythonpath = libs/common tests/architecture (el núcleo del helper no tiene dependencias)
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
- Workers: el mismo JSON en `/tmp/health.json`, más la hora. Las críticas son `mongodb`, `rabbitmq` y `topology` (la topología verificada, D12):

  ```json
  {"service": "ingest-consumer", "status": "ok",
   "dependencies": {"rabbitmq": "ok", "topology": "ok", "mongodb": "ok"},
   "info": {}, "time": "2026-11-16T21:20:03+00:00"}
  ```

- Más adelante, el `recommender` agrega `"ready": true/false`.

### Workers y latido (F3)

La conexión de pika (`BlockingConnection`) no es thread-safe, y solo atiende el socket (mensajes y heartbeat AMQP) cuando el hilo dueño llama a `process_data_events`. Por eso el trabajo se reparte así:

```
hilo principal (dueño de pika, sync/worker.py)    hilo del latido (sync/heartbeat.py, cada 10 s)
process_data_events(time_limit=1) en bucle        lee HealthState: un reporte de más de 30 s es "error"
HealthState.report("rabbitmq" / "topology") ──▶   ping a Mongo con el mismo MongoClient (thread-safe)
verify_topology cada 10 s                         escribe /tmp/health.json (tmp + os.replace)
decide D14: reconecta o termina con código 1      solo informa; nunca termina el proceso
```

- **Restricción para la lógica de negocio:** un worker que hace trabajo largo tiene que llamar a `process_data_events` entre partes del trabajo, o hacerlo en otro hilo y confirmar mensajes con `add_callback_threadsafe`. Si no, con más de 30 s sin reportar, su `rabbitmq` pasa a `error`, y si sigue sin atender la conexión, el broker la corta.
- **Los 30 s son más estrictos que el corte real del broker.** Medido con el proceso congelado (SIGSTOP): RabbitMQ registró `missed heartbeats from client, timeout: 30s` y cortó la conexión **unos 88 s** después. El latido avisa a los 30 s, cuando el worker ya no cumple el intervalo de heartbeat negociado, aunque la conexión siga viva un rato más.
- **Mongo lo comprueba el latido**, con `serverSelectionTimeoutMS` y `connectTimeoutMS` de 3 s. Con el default de pymongo (30 s), un ping a un Mongo caído tardaría más que el intervalo del latido. Al arrancar, el hilo principal espera a Mongo para detectar credenciales rechazadas, que son irrecuperables. Después, una caída de Mongo solo la informa el latido: pymongo se reconecta solo con el mismo cliente.
- **El latido borra la nota al arrancar**, y su primer latido sale antes de que el hilo principal conecte (con `error`, logueado como "arrancando"). Un reinicio de Docker conserva `/tmp`, y una nota vieja con `ok` daría *healthy* antes de comprobar nada. En el bucle de reinicios por topología faltante no hubo ningún *healthy* falso.
- **Python como PID 1 ignora SIGTERM si no instala un handler:** `docker stop` termina matándolo con SIGKILL (medido: código 137 sin handler, 0 con handler). `worker.main` instala uno.
- **`up --wait` y `topology-init`: resuelto.** Con los workers dependiendo de `topology-init` con `service_completed_successfully`, `up -d --build --wait` termina con 0 (repetido varias veces).

Casos de falla comprobados contra los contenedores reales (`docker stop`/`start` directo, sin compose):

| Caso | Qué pasó |
| :-- | :-- |
| Mongo caído 60 s | El latido pasa a `mongodb: error` a los ~4 s; Docker marca *unhealthy* a los ~26 s (3 healthchecks); sin reinicios. Al volver Mongo, `ok` a los ~3 s y *healthy* en el siguiente healthcheck. |
| Rabbit caído 45 s | `ConnectionClosedByBroker` (320 `CONNECTION_FORCED`), reintentos de 1 a 10 s (incluido `gaierror`), *unhealthy* sin reinicios. Al volver, reconexión, nueva verificación de la topología y *healthy* (~17 s para que el broker acepte AMQP y llegue el reintento). |
| Contraseña de Rabbit incorrecta | `ProbableAuthenticationError` (403 `ACCESS_REFUSED`), código 1 sin reintentar. |
| Contraseña de Mongo incorrecta | `OperationFailure` (código 18, `Authentication failed`), código 1 sin reintentar. |
| Cola borrada (`rabbitmqctl delete_queue`) | `TopologyError` (404 `NOT_FOUND`) en la verificación siguiente (~2 s), código 1 y bucle de reinicios sin *healthy*. `docker compose up -d` vuelve a correr `topology-init`, y el siguiente reinicio de los workers arranca bien. |
| Proceso congelado (SIGSTOP 90 s) | `latido vencido: escrito hace 90 s` en `State.Health.Log`; *unhealthy* a los ~60 s (30 s de nota + 3 healthchecks); **sin reinicio** (límite aceptado en D14). Con SIGCONT: `StreamLostError` (el broker ya había cortado), reconexión en 16 ms y *healthy*. |

- **`up --wait` durante un bucle de reinicios falla enseguida** (`container ... is unhealthy`): `--wait` toma *unhealthy* como error y no espera a que el servicio se recupere. Un segundo `up -d --wait`, con la topología ya restaurada, termina con 0.
- **`docker kill --signal` desactiva `unless-stopped`** (encontrado en F4). Cualquier señal, aunque sea inofensiva como SIGCONT, marca el contenedor como detenido a mano. Si después el proceso termina, Docker no lo reinicia, y tampoco lo levanta cuando vuelve el daemon. Comprobado con dos contenedores iguales: el que recibió SIGCONT quedó en `exited` y el otro se reinició. Así quedó el `ingest-consumer` tras la prueba de SIGSTOP, y Docker Desktop no lo levantó al día siguiente. **Después de inyectar una falla con `docker kill --signal`, hay que hacer `docker compose restart <servicio>`**, que borra la marca. Hay que tenerlo en cuenta en F6.

### Servicios HTTP (F4)

`backend` y `recommender` usan `aio/` (D9): un solo hilo con un event loop, donde aio-pika atiende la conexión (heartbeat AMQP incluido) mientras el loop esté libre. Diseño confirmado con el usuario:

1. **`/health` devuelve la "foto" del monitor**, sin chequear en el momento. `aio/monitor.py` corre los checks cada 10 s, en paralelo y con un timeout de 5 s cada uno. `/health` responde 200, o 503 si falla una crítica, si todavía no hubo un chequeo ("arrancando") o si la foto tiene más de 30 s. Así, el costo de `/health` no depende de cuántos lo consulten: Docker, el `frontend` (F5) por cada usuario, y el `backend` al `recommender`.
2. **El servidor responde desde el primer segundo**, y Mongo y Rabbit se conectan en paralelo en segundo plano. El monitor vuelve a chequear apenas se abren las conexiones: *healthy* a los ~8 s del arranque.
3. **D14 en un servidor HTTP:** una tarea no puede terminar el proceso con `sys.exit`. `on_fatal` hace `server.should_exit = True`; uvicorn cierra en orden (lifespan, conexiones) y el proceso termina con código 1. uvicorn maneja SIGTERM por su cuenta.
4. **FastAPI vive en cada servicio** (`requirements.txt`). El helper sigue sin framework web, y las ~30 líneas de arranque se repiten en los dos `main.py`.

- **Regla del event loop:** nunca bloquearlo con I/O sincrónica o cálculo pesado. El entrenamiento del `recommender` va a ir en un proceso o hilo aparte (`run_in_executor`). Con el loop bloqueado, `/health` no responde y el servicio queda *unhealthy* sin reinicio (medido abajo).
- **`connect_robust` no reintenta la primera conexión** (medido: falla al instante con el broker inalcanzable); solo reconecta después. `aio/rabbit.connect` reintenta la primera, como `sync/`.
- **En una conexión robusta, `is_closed` no indica si está conectada:** solo dice si se llamó a `close()`. Con el broker caído quedaba en `False`, y `/health` mostraba `rabbitmq: ok`. El estado real es el evento `connected`.
- Irrecuperables de aiormq: `AuthenticationError`, `ProbableAuthenticationError` y `ConnectionNotAllowed`. Una cola faltante da `ChannelNotFoundEntity`, que cierra el canal pero no la conexión.
- **Logs:** aiormq loguea un ERROR con traceback por cada corte, y queda en CRITICAL. aio-pika queda en WARNING (una línea por intento de reconexión, cada 5 s). httpx queda en WARNING. El access log de uvicorn oculta `/health`. `client_properties.connection_name` nombra cada conexión en `rabbitmqctl list_connections`, también las de pika.
- Versiones: `fastapi==0.162.0` (la última con más de dos semanas al implementar), `uvicorn==0.54.0`, `httpx==0.28.1`. Las dependencias transitivas (starlette, pydantic) no están fijadas.

Casos de falla comprobados (`docker stop`/`start` directo):

| Caso | Qué pasó |
| :-- | :-- |
| `recommender` caído 40 s | El `backend` responde 200 y sigue *healthy* todo el tiempo; `info.recommender: error` a los ~8 s y `ok` cuando vuelve (D12). |
| Mongo caído 60 s | 503 con `mongodb: error` a los ~7 s; *unhealthy* a los ~31 s; sin reinicios. `ok` a los ~12 s de que vuelve Mongo. El `info` del `backend` encadena: el `recommender` da 503 y el `backend` lo informa. |
| Rabbit caído 30 s | 503 con `rabbitmq` y `topology` en `error`; `connect_robust` reintenta cada 5 s (incluido `Name or service not known`); `ok` a los ~22 s de que vuelve el broker; sin reinicios. |
| Contraseña de Rabbit o de Mongo incorrecta | `ProbableAuthenticationError` / `OperationFailure` (18): apagado ordenado de uvicorn y código 1. |
| Cola borrada | `TopologyError` en el chequeo siguiente, código 1 y bucle de reinicios en los dos servicios. `docker compose up -d` vuelve a correr `topology-init` y se recuperan en ~14 s. |
| Proceso congelado (SIGSTOP) | `/health` sin respuesta (`TimeoutError`); *unhealthy* a los ~48 s (3 healthchecks con timeout de 5 s); sin reinicio (límite de D14). Con SIGCONT vuelve a 200 sin reconectar: 48 s es menos que el corte del broker (~88 s, F3). |

### Frontend (F5)

Diseño confirmado con el usuario:

1. **El contexto de build es `services/frontend`**, no la raíz: D4 existe para compartir el helper de Python, y el frontend no lo usa. Tiene su propio `.dockerignore` (el de la raíz solo aplica a su contexto).
2. **La pantalla consulta `/api/health` cada 5 s** (barato gracias a la foto del monitor de F4). Distingue tres casos: el `backend` respondió con 200 ("Funcionando"), respondió con 503 ("Con problemas", con la lista de dependencias), o nginx respondió con 502/504, que es HTML y no JSON ("Backend no disponible").
3. **El healthcheck le pide `/` a su propio nginx** con `wget` (la imagen alpine no trae Python ni curl). Sano significa que nginx sirve el build, sin importar el `backend` (D12).
4. **Matriz:** el `frontend` resuelve `backend` y no resuelve `mongodb`, `rabbitmq` ni `recommender` (criterio 4). Sale a internet, porque `public-net` no puede ser `internal` (el `backend` sale por ella); queda registrado en la matriz para que un cambio se vea en el diff. Como la imagen no tiene Python, `SH_PROBE` prueba lo mismo con `getent` y `nc` de busybox.

- Imágenes: `node:26-alpine` (LTS activa) compila y `nginx:1.30-alpine` (estable) sirve; Node no llega a la imagen final. Paquetes con versión fija y `package-lock.json` (`npm ci`): React 19.1.10, Vite 8.3.5, TypeScript 7.0.2, `@vitejs/plugin-react` 6.2.1, todos con más de dos semanas al implementar. El lockfile se generó en un contenedor (`npm install --package-lock-only`): no hace falta Node en el host.
- `npm run build` corre `tsc --noEmit` antes de `vite build`: comprobado que un error de tipos corta el build de la imagen.
- **Sin la variable en `proxy_pass`, nginx no arranca si el `backend` no existe:** `[emerg] host not found in upstream`, código 1 (comprobado). Con `set $backend` + `resolver`, resuelve en cada pedido.
- `/api/health` con el `backend` recién detenido da **504** en el primer pedido (la IP en caché ya no contesta y vence `proxy_connect_timeout` de 3 s) y después **502** (`backend could not be resolved`). La pantalla trata los dos como "no disponible".

Casos comprobados contra los contenedores reales, desde el host:

| Caso | Qué pasó |
| :-- | :-- |
| `backend` detenido | `frontend` *healthy* y `/` con 200 todo el tiempo; `/api/health` 504 y después 502. Al volver el `backend`, 200 en ≤ 4 s. |
| `frontend` reiniciado con el `backend` caído | nginx levanta y queda *healthy*; `/api/health` con 502 hasta que vuelve el `backend`. |
| `backend` recreado con otra IP (`172.24.0.3` → `.5`, con dos contenedores ocupando direcciones) | nginx llega a la IP nueva en ≤ 3 s, sin reiniciar el `frontend`. |
| **Criterio 1 en un clon limpio** (`git clone` de la rama, `COMPOSE_PROJECT_NAME=dcicflix-limpio`, `FRONTEND_PORT=8081`) | `up --build --wait` con código 0 en 264 s (build de todas las imágenes y carga del dataset desde cero: 19.842 películas y 61.488 reseñas); los 108 tests pasan contra ese proyecto, en el puerto 8081. Bajado con `down -v`. |

`COMPOSE_PROJECT_NAME` tiene prioridad sobre el `name:` del compose: sirve para levantar una copia aislada (otros contenedores, redes y volúmenes) y correr los tests contra ella.

### Persistencia y reconexión (F6)

Diseño confirmado con el usuario: dos tests `slow` en `test_resiliencia.py`, fuera del `pytest` habitual (`addopts = -m "not slow"`; se corren con `pytest -m slow`, que pisa al de `addopts`). Bajan el sistema y tardan ~2,5 min. Cada uno lo deja levantado y sano. Nunca usan `down -v`.

1. **Persistencia (criterio 6), con centinelas.** Contar documentos no alcanza: con el volumen perdido, `mongo-init.sh` recarga el dataset y las cantidades dan igual. Antes del `down`, el test inserta un documento con un uuid nuevo (colección `_test_persistencia`) y publica un mensaje persistente con otro uuid en `interactions.errors`, que no consume nadie. Después de `down` + `up -d --wait`, exige todo *healthy*, las mismas cantidades (detecta una carga duplicada) y los dos centinelas. Al final borra la colección y vacía la cola. Si la cola ya tenía mensajes, el test se saltea en lugar de tocarlos.
2. **Reconexión.** `docker compose stop mongodb rabbitmq` con todo corriendo. El test espera a que los cuatro servicios Python estén *unhealthy* (una caída que nadie nota no prueba nada) y comprueba D12 durante la caída: `frontend` *healthy* y `/api/health` con 503 y `mongodb`/`rabbitmq` en `error`. Después hace `start` y espera a que todo vuelva. Exige `RestartCount` sin cambios (D14: reconectar no es reiniciar) y que `topology-init` no haya vuelto a correr: la topología sale del volumen de Rabbit.

- **`docker compose stop <servicio>` no detiene a los que dependen de él** (Compose 5.4, comprobado): el test puede usar Compose, sin `docker stop` directo.
- Pika publica con `confirm_delivery()` y `delivery_mode=2`: cuando `basic_publish` vuelve, el broker ya guardó el mensaje. Rabbit no trae un cliente de línea de comandos que publique (sin panel, D8), así que el test usa pika dentro del `ingest-consumer`.
- Tiempos medidos: `down` + `up` en 59 s. Con las dos dependencias caídas, los servicios pasan a *unhealthy* a los ~28-31 s y vuelven a *healthy* ~30-48 s después del `start`. El último suele ser un worker, por la espera exponencial de hasta 10 s de `sync/rabbit`. Rabbit volvió con otra IP (`.4` → `.3`), y todos la resolvieron solos.
- `RestartCount` se pone en cero cuando se reinicia el daemon. El test compara antes y después dentro de la misma corrida, así que no le afecta.

Comprobado que los tests fallan cuando tienen que fallar:

| Falla inyectada | Qué pasó |
| :-- | :-- |
| SIGTERM al PID 1 del `ingest-consumer` durante la caída (`unless-stopped` lo reinicia y termina *healthy*) | Falla: `reconectar no tendría que reiniciar el contenedor (D14): {'ingest-consumer': (0, 1)}`. Un test que mirara solo el estado final habría pasado. |
| `down -v` en lugar de `down` (en una copia aislada, `COMPOSE_PROJECT_NAME=dcicflix-f6`) | **La comparación de cantidades pasó** (el dataset se recargó) y el test falló en el centinela de Mongo: `None == {'_id': '8502…'}`. |
| Solo `rabbitmq-data` borrado entre `down` y `up` | Todo vuelve a *healthy* (`topology-init` recrea la topología), y el test falla en el centinela de Rabbit: `0 == 1` mensajes. |

**Reinicio de Docker Desktop** (`docker desktop restart`, prueba manual una vez): es el caso en que Docker levanta los contenedores `unless-stopped` sin el orden de `depends_on`, y `topology-init` (`restart: "no"`) no corre.

- Docker registró el arranque de los 7 en 3 s (Rabbit, Mongo, `frontend`, `recommender`, `backend`, workers), pero los procesos loguearon recién 30-45 s después, mientras terminaba de levantar la VM. El daemon respondió a los 109 s del pedido de reinicio.
- El `start_period` se cuenta desde el arranque del contenedor: con la VM todavía lenta, el `cleaning-agent` apareció *unhealthy* antes de llegar a conectar. Es transitorio.
- Los servicios arrancaron antes de que Rabbit aceptara AMQP: el `backend` reintentó 4 veces (1, 2, 4 y 8 s) y conectó. Todo *healthy* a los 39 s de que respondió el daemon, con 0 reinicios. `topology-init` no corrió, y la topología del volumen alcanzó.
- Es la confirmación de que **`depends_on` es comodidad y los reintentos son la garantía**.

### Modo desarrollo (F7)

Diseño confirmado con el usuario (D5): `frontend-dev` con perfil `dev`, puerto configurable (`FRONTEND_DEV_PORT`, por defecto 5173) y la etapa `dev` en el mismo Dockerfile, sin cambiar el `up` normal. **Los tests de arquitectura cubren solo el modo producción**: no hay fila de `frontend-dev` en `REACHABILITY` ni tests estáticos con el perfil.

```
FROM node:26-alpine AS deps   npm ci
FROM deps AS dev              CMD npm run dev     ← solo con target: dev (frontend-dev)
FROM deps AS build            COPY . · npm run build
FROM nginx:1.30-alpine        COPY --from=build   ← última etapa: la del frontend normal
```

- **El `up` normal no cambia** (comprobado): sin el perfil, `frontend-dev` no figura en `compose config`. BuildKit construye solo las etapas que necesita la última (`deps`, `build` y nginx), y la imagen del `frontend` salió idéntica a la anterior: no se recreó. Las opciones de `server` de `vite.config.ts` solo aplican al servidor de desarrollo.
- `vite.config.ts` lee sus variables con `loadEnv(mode, ".", "DEV_")`, no con `process.env`. El `tsconfig` incluye `vite.config.ts` solo con los tipos de `vite/client`, y `process` rompería el `tsc --noEmit` del build. No hace falta `@types/node` ni tocar el lockfile. Las variables no llevan el prefijo `VITE_`, porque Vite las incluiría en el código del navegador.
- `server.host: true`: por defecto Vite escucha solo en el `localhost` del contenedor.
- `test_dockerfiles_con_tag_fijo` ignora los `FROM` que nombran una etapa anterior (`FROM deps AS dev`). Comprobado que sigue rechazando `FROM python` sin tag.

Comprobado contra los contenedores reales, desde el host:

| Caso | Qué pasó |
| :-- | :-- |
| Recarga en caliente | Un cliente del websocket de Vite, conectado por el puerto publicado como el navegador (`101 Switching Protocols`, `connected`), recibió `js-update` de `/src/App.tsx` en menos de 1 s después de guardar. El módulo servido ya traía el cambio. |
| **Sin polling** (`FRONTEND_DEV_POLLING=false`) | Ningún `update`, ningún `hmr update` en el log, y Vite siguió sirviendo la versión vieja desde su caché. Con el código en Windows, el polling hace falta. |
| `FRONTEND_DEV_PORT=5174` | Publicado `5174->5173`, y la recarga funciona por el 5174. **`hmr.clientPort` no hace falta:** con `hmrPort = null`, el cliente abre el websocket en el puerto de la página (`importMetaUrl.port`). Lo saqué del diseño propuesto. |
| `backend` detenido | `/` con 200, `/api/health` con **502 `text/plain`** (`getaddrinfo ENOTFOUND backend` en el log) y `frontend-dev` *healthy*. Como no es JSON, la pantalla muestra "Backend no disponible", igual que con nginx. Al volver, 200. |
| `backend` recreado (test de persistencia con el perfil levantado) | `frontend-dev` llegó al contenedor nuevo sin reiniciarse: Vite resuelve el nombre en cada pedido. |
| Error de tipos en `App.tsx` | Vite lo sirvió con 200 y lo mandó por la recarga: **no chequea tipos**. El error aparece recién en el build de producción. |
| `docker compose stop frontend-dev` | 3 s, código 143 (SIGTERM): no hace falta esperar al SIGKILL. |

- **El volumen anónimo de `node_modules` sobrevive a `up --build --force-recreate`:** una marca dejada adentro siguió ahí. Si cambia `package.json`, hace falta `-V` (`--renew-anon-volumes`), y entonces la marca desaparece. `-V` deja huérfano el volumen anterior: se borra con `docker volume rm <id>`, no con `docker volume prune`, que borraría los volúmenes huérfanos de otros proyectos.
- **Docker crea `services/frontend/node_modules` vacía en el host:** es el punto de montaje del volumen anónimo dentro del montaje del código. Ya figura en `.gitignore` y en el `.dockerignore` del frontend.
- **`docker compose down` sin el perfil no toca `frontend-dev`,** y `public-net` queda en uso (`Resource is still in use`, código 0). Para bajar todo: `docker compose --profile dev down`. El test `slow` de persistencia exige que no queden contenedores de los servicios de producción, y por eso corre igual con el perfil levantado (comprobado: los 2 pasan, y `frontend-dev` sigue sano al final).
- `docker compose ps` lista `frontend-dev` aunque no se pase el perfil. La suite normal pasa igual con él levantado: los tests recorren los servicios de `compose config`.

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
  - Recuperables (`sync/rabbit.py`): `AMQPConnectionError` y **`OSError`**. Con el contenedor de `rabbitmq` detenido, su nombre deja de resolver y pika lanza `socket.gaierror`, que no es un error AMQP (encontrado en F2). Espera exponencial de 1 a 10 s.
  - Irrecuperables: credenciales rechazadas (`ProbableAuthenticationError` y afines, subclases de `AMQPConnectionError` que se excluyen del reintento), canal cerrado por el broker (`PRECONDITION_FAILED`) y topología faltante.
  - Comprobado en F2 contra el broker real: idempotencia, variable faltante, contraseña incorrecta (falla sin reintentar), cola con otros argumentos (406), broker caído que vuelve (reintenta y termina bien) y broker caído 60 s (código 1).
- **`up --wait` y `topology-init`:** `--wait` da error si un contenedor termina mientras espera, aunque sea con código 0, salvo que otro servicio dependa de él con `service_completed_successfully` (comprobado). Por eso en F2, sin dependientes, `--wait` puede fallar según los tiempos; desde F3 los workers dependen de `topology-init` y deja de pasar (comprobado en F3).
- `verify_topology` comprueba exchanges y colas con declaraciones pasivas. AMQP no permite consultar bindings: los comprueba el test de arquitectura con `rabbitmqctl list_bindings`.
- RabbitMQ 4.1 agrega `x-queue-type: classic` a cada cola: el test exige los argumentos de `topology.py` sin pedir que sean los únicos.

### Configuración (D15)

- Cada servicio recibe **solo sus variables** por `environment:`, con anclas YAML (`x-mongo-env`, `x-rabbit-env`). Sin `env_file` común: la key del LLM llega solo a `backend` y `cleaning-agent`.
- `config.py` arma la URI de Mongo con `authSource=admin` y la contraseña escapada con `quote_plus`.
- `MONGO_DB=peliculas-proyectos` fijo en el compose, fuera de `.env`: el `mongo-init.sh` lo tiene escrito en el código.
- `LLM_API_KEY` es opcional en `config.py`; el resto de las variables son obligatorias.
- Mongo y Rabbit crean el usuario solo con el volumen vacío: cambiar credenciales exige `docker compose down -v`. Se documenta en `.env.example`.
- Variables: `FRONTEND_PORT`, `FRONTEND_DEV_PORT` y `FRONTEND_DEV_POLLING` (F7), `MONGO_USER`, `MONGO_PASSWORD`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `LLM_API_KEY`, `LOG_LEVEL`.

### Verificación de la arquitectura (D16)

`tests/architecture/`, con pytest en el host (Python 3.12 + `pip install -r tests/requirements.txt`). Llama a `docker compose` con `subprocess`.

| Marca | Necesita `up` | Verifica |
| :-- | :-- | :-- |
| `static` | No: lee `docker compose config --format json` | Solo el `frontend` publica puertos; todos declaran `networks:` y no existe `default`; `internal-net` es `internal: true`; tags fijos; `restart` según la tabla de arranque |
| `dynamic` | Sí | Todos *healthy* y `topology-init` en `Exited (0)`; `localhost:8080/api/health` → 200; matriz de alcance y aislamiento; topología del broker igual a `topology.py` |
| `slow` | Sí; fuera del `pytest` habitual, con `pytest -m slow` | Persistencia: tras `down` + `up`, centinelas de Mongo y Rabbit y cantidad de documentos igual. Reconexión: `stop` y `start` de Mongo y Rabbit, de vuelta a *healthy* sin reinicios |

- Lo esperado vive en `tests/architecture/spec.py` (redes, redes internas, servicios con puerto, servicios de una sola vez, política de reinicio); los tests solo comparan.
- Uso: `python -m venv .venv`, `pip install -r tests/requirements.txt`, `docker compose up -d --wait` y `pytest` (o `pytest -m static`). Los `slow`, aparte: `pytest -m slow`.
- `compose config` omite las redes que ningún servicio usa: el test de redes compara por inclusión, y la existencia de cada conexión la prueba la matriz.
- **La tabla de comunicación es datos del test:** una matriz `REACHABILITY` (qué resuelve cada servicio, qué no, y si sale a internet) genera los tests de alcance y aislamiento. Cambiar la arquitectura obliga a cambiar esa tabla.
- La topología se compara importando `dcicflix_common.topology` contra `rabbitmqctl list_queues` y `list_exchanges`.
- Los tests de salida a internet se saltean con aviso si la máquina no tiene conexión.
- **Matriz en F3** (`test_reachability.py`): un solo `docker compose exec` por servicio, que prueba todos los nombres y destinos y devuelve un JSON. Los nombres de servicios que todavía no existen (`frontend`) se saltean con aviso, en lugar de pasar sin probar nada. Un test estático exige una fila en `REACHABILITY` por cada servicio propio de larga vida.
- **La salida a internet se prueba por IP (`1.1.1.1:443`) y por nombre (`one.one.one.one:443`).** Medido: en un contenedor que solo está en `internal-net`, Docker ni siquiera resuelve nombres externos (`Temporary failure in name resolution`). Probar solo por nombre no distinguiría "sin DNS" de "sin ruta". Por IP da `Network is unreachable`: el aislamiento es real.
- Comprobado que los tests fallan con la matriz equivocada, y que se saltean con un destino inalcanzable desde el host.
- **En F4:** el `backend` resuelve `mongodb`, `rabbitmq` y `recommender` y sale a internet (criterio 4: traducción y chat); el `recommender` no sale y no resuelve `frontend`. `test_health_http` pide `/health` desde adentro de cada contenedor y exige las críticas y las informativas de `spec.HTTP_HEALTH_INFO`.
- Cada fase agrega los tests de lo que construye.

## Fases de implementación

Cada fase es un commit (o pocos), termina con `docker compose up --build` sano y suma sus tests. Ninguna depende de una posterior.

| Fase | Qué se construye | Se verifica con |
| :-- | :-- | :-- |
| **F1. Base e infraestructura** | `.gitattributes` (antes de commitear `dataset/`), `.gitignore`, `.dockerignore`, `.env.example`; commit de `dataset/` y `docs/`; `docker-compose.yml` con `mongodb`, `rabbitmq`, las 3 redes y los volúmenes; esqueleto de `tests/architecture/` con los tests `static` | Mongo y Rabbit *healthy*; `movies` y `reviews` cargadas; `pytest -m static` en verde |
| **F2. Helper común y topología** | `libs/common`: `config`, `logging`, `topology`, `sync/rabbit`; servicio `topology-init`; tests unitarios del helper; cambios en el README | `topology-init` en `Exited (0)`; test de topología |
| **F3. Workers** | `health`, `sync/mongo`, `sync/heartbeat` y `sync/healthcheck` (cada pieza entra en la fase que la ejercita); `ingest-consumer` y `cleaning-agent` con latido y la política de D14 | *healthy* por latido; matriz de alcance para ambos; salida a internet solo del `cleaning-agent` |
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

### Cambios al README (hechos en F2)

- `topology-init` en la tabla de servicios y en el arranque en frío; `Exited (0)` aclarado como normal.
- "Cada servicio declara al iniciar las colas que usa" reemplazado por "`topology-init` declara la topología; los servicios la verifican", con la cola de errores y el fanout de `data.cleaned`.
- Cómo correr los tests de arquitectura, `.env` opcional y API key del LLM opcional.
- Tecnologías (D2, D3) en la sección de servicios, en lugar de figurar como pendiente; la API key para la evaluación agregada a "Pendiente".
