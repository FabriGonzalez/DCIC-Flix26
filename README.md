# DCIC-Flix26

Plataforma web de catálogo cinematográfico con microservicios, agente de limpieza de datos y motor de recomendaciones, orquestada con Docker Compose.

Proyecto final de Tópicos Avanzados de Desarrollo Web (DCIC, UNS), edición 2026.

> **Estado del documento:** describe el diseño de arquitectura acordado por el grupo. La implementación está en curso: el esqueleto de contenedores sigue el plan de [docs/esqueleto-contenedores.md](docs/esqueleto-contenedores.md). Las secciones que dependen de la funcionalidad están listadas en [Pendiente](#pendiente).

## Ejecución

```bash
docker compose up --build
```

No requiere pasos manuales: la carga del dataset, la declaración de colas, la limpieza y el entrenamiento inicial se coordinan entre los contenedores.

La aplicación queda en **http://localhost:8080** (el puerto se cambia con `FRONTEND_PORT` en `.env`). Por ahora muestra el estado del sistema, que consulta a `/api/health` cada 5 s.

- **`.env` es opcional.** Sin él se usan valores de desarrollo. Para cambiarlos, copiar [.env.example](.env.example) a `.env`. La API key del LLM también es opcional: sin ella, las funciones que usan el LLM quedan deshabilitadas.
- **`topology-init` en `Exited (0)` es lo esperado:** declara las colas de RabbitMQ y termina.
- `backend` y `recommender` exponen `GET /health` en el puerto 8000, sin publicar en el host. Los workers sin HTTP (`ingest-consumer`, `cleaning-agent`) dejan su estado en un archivo de latido: `docker compose exec ingest-consumer cat /tmp/health.json`. Si un servicio está *unhealthy*, el motivo aparece en `docker inspect --format '{{json .State.Health.Log}}' <contenedor>`.
- La primera carga del dataset tarda alrededor de un minuto. Para recargarlo desde cero: `docker compose down -v`.

### Modo desarrollo del frontend

```bash
docker compose --profile dev up --build
```

Además de lo anterior, levanta `frontend-dev`: Vite en **http://localhost:5173** (`FRONTEND_DEV_PORT`), con el código de `services/frontend` montado y recarga en caliente al guardar. `/api` llega al `backend` igual que en producción.

- Vite no chequea tipos: los errores de TypeScript aparecen recién en el build de producción (`docker compose up --build frontend`).
- Si cambia `package.json`, los `node_modules` viejos siguen en un volumen: `docker compose --profile dev up --build -V frontend-dev`.
- Para bajarlo: `docker compose --profile dev down`. Un `down` sin el perfil no toca `frontend-dev`.

### Verificación de la arquitectura

```bash
python -m venv .venv                        # Python 3.12
.venv/Scripts/activate                      # en Linux o macOS: source .venv/bin/activate
pip install -r tests/requirements.txt
pytest -m static                            # no necesita nada levantado
docker compose up -d --wait && pytest       # todo menos slow, con el sistema levantado
pytest -m slow                              # persistencia y reconexión: baja y levanta el sistema (~2,5 min)
```

La arquitectura esperada (redes, puertos, servicios y qué nombres resuelve y alcanza cada uno) está como datos en [tests/architecture/spec.py](tests/architecture/spec.py), y la topología de RabbitMQ en [topology.py](libs/common/dcicflix_common/topology.py).

## Servicios

| Servicio | Responsabilidad |
| :--- | :--- |
| `frontend` | Interfaz web. Solo se comunica con `backend`. |
| `backend` | Gateway/API: lecturas del catálogo, publicación de interacciones, estado del sistema, auditoría y proxy hacia `recommender`. |
| `mongodb` | Base de datos (imagen oficial). Carga el dataset inicial desde `dataset/`. |
| `rabbitmq` | Message broker (imagen oficial). |
| `topology-init` | Declara exchanges y colas de RabbitMQ al arrancar y termina. |
| `ingest-consumer` | Worker sin API HTTP: consume votos y reseñas de la cola y los persiste en MongoDB. |
| `cleaning-agent` | Diagnostica y sanea el dataset, registra la auditoría y emite la señal de datos limpios. |
| `recommender` | Entrena o indexa al recibir la señal y sirve recomendaciones desde estructuras en memoria. |

Tecnologías: los servicios propios del lado servidor están en Python 3.12 (FastAPI para `backend` y `recommender`) y comparten un helper en [libs/common](libs/common). El `frontend` usa React + TypeScript (Vite), servido por nginx.

El `backend` concentra varias responsabilidades de lectura a propósito: actúa como único punto de entrada para el `frontend`, lo que simplifica el aislamiento de redes.

## Arquitectura de redes

```
        navegador
            │  (único puerto publicado)
      ┌─────▼─────┐
      │ frontend  │   sirve la UI y reenvía /api al backend
      └─────┬─────┘
            │                         public-net
      ┌─────▼─────┐
      │  backend  │──────────▶ API del LLM (traducción, chat)
      └─────┬─────┘
 ───────────┼──────────────────────── internal-net (sin salida a internet)
            │
   ┌────────┼──────────┬──────────────┬───────────────┐
   │        │          │              │               │
┌──▼────┐ ┌─▼──────┐ ┌─▼───────────┐ ┌▼────────────┐ ┌▼─────────────┐
│mongodb│ │rabbitmq│ │ recommender │ │ingest-      │ │cleaning-agent│──▶ API del LLM
│       │ │        │ │             │ │consumer     │ │              │   (egress-net)
└───────┘ └────────┘ └─────────────┘ └─────────────┘ └──────────────┘
```

| Red | Servicios | Propósito |
| :--- | :--- | :--- |
| `public-net` | `frontend`, `backend` | Única vía del `frontend` hacia el sistema. |
| `internal-net` (`internal: true`) | `backend`, `mongodb`, `rabbitmq`, `recommender`, `ingest-consumer`, `cleaning-agent` | Datos y mensajería, sin salida a internet. |
| `egress-net` | `cleaning-agent` | Salida del agente hacia la API del LLM. |

Justificación:

- **El `frontend` no comparte ninguna red con `mongodb`**, por lo que no puede conectarse ni resolver su nombre de host. Tampoco alcanza a `rabbitmq` ni a `recommender`.
- **`internal-net` no tiene salida a internet.** `mongodb` y `rabbitmq` quedan inaccesibles desde afuera y sin capacidad de iniciar conexiones externas.
- **`egress-net` existe porque el LLM se consume por API externa.** El `backend` sale por `public-net`; el `cleaning-agent` necesita una red propia con salida.
- **Solo se publica el puerto del `frontend`.** Este reenvía `/api` al `backend`, que no queda expuesto al host.

## Comunicación entre servicios

| Origen | Destino | Mecanismo | Contenido |
| :--- | :--- | :--- | :--- |
| `frontend` | `backend` | HTTP | Catálogo, estado, votos, recomendaciones, auditoría |
| `backend` | `mongodb` | Lectura | Catálogo, reseñas, auditoría, marca de limpieza |
| `backend` | `rabbitmq` | Publica | Votos y reseñas |
| `backend` | `recommender` | HTTP | Recomendaciones y `/health` |
| `ingest-consumer` | `rabbitmq`, `mongodb` | Consume, escribe | Persistencia de interacciones |
| `cleaning-agent` | `mongodb` | Lectura y escritura | Limpieza, auditoría, marca de limpieza |
| `cleaning-agent` | `rabbitmq` | Publica | Evento `data.cleaned` |
| `recommender` | `rabbitmq`, `mongodb` | Consume, lectura | Señal de limpieza, datos para entrenar |

Criterio para elegir el mecanismo:

- **RabbitMQ** para trabajo o avisos que no se pueden perder: guardar un voto, anunciar que los datos están limpios.
- **HTTP** para consultas que necesitan respuesta inmediata: catálogo, recomendaciones (objetivo < 100 ms), estado y salud.

### Mensajería

| Nombre | Tipo | Publica | Consume | Uso |
| :--- | :--- | :--- | :--- | :--- |
| `interactions` | Cola durable | `backend` | `ingest-consumer` | Votos con reseña. Mensajes persistentes y confirmación manual. |
| `data.cleaned` | Evento | `cleaning-agent` | `recommender` | Dispara el entrenamiento o indexación inicial. |

Los mensajes de `interactions` que no se pueden guardar se derivan por dead-letter a la cola `interactions.errors`. `data.cleaned` es un exchange fanout: cada suscriptor tiene su propia cola (hoy, `recommender.data-cleaned`).

`topology-init` declara toda la topología, definida en un único archivo ([topology.py](libs/common/dcicflix_common/topology.py)), y los servicios la verifican al arrancar y cada 10 s, sin declararla. Así hay un solo responsable y no hay configuración manual del broker. Si falta una cola o un exchange, el servicio termina y Docker lo reinicia hasta que la topología vuelva: `docker compose up -d` corre otra vez `topology-init`.

### Estado del sistema

El estado que ve el `frontend` se arma a partir de dos fuentes con distinta naturaleza:

| Fuente | Dónde vive | Valores | Naturaleza |
| :--- | :--- | :--- | :--- |
| Marca de limpieza | MongoDB (persiste en el volumen) | `pending`, `running`, `done` | Duradera: sobrevive a reinicios. |
| Salud del recomendador | `GET /health` de `recommender` | listo o no | Del proceso: se recalcula en cada arranque. |

El `backend` las combina en `GET /status`:

| Estado | Condición | Efecto en el `frontend` |
| :--- | :--- | :--- |
| `cleaning` | Marca de limpieza distinta de `done` | Catálogo navegable con aviso; recomendaciones y votos deshabilitados. |
| `indexing` | Marca `done`, recomendador no listo | Igual que `cleaning`, con el mensaje correspondiente. |
| `ready` | Marca `done`, recomendador listo | Todas las funciones habilitadas. |

Los eventos disparan trabajo entre servicios; `GET /status` responde siempre a partir del estado real. Por eso un reinicio del `backend` o del `recommender` no deja el sistema en un estado inconsistente.

El `frontend` consulta `GET /status` cada pocos segundos mientras el estado no sea `ready`, y luego deja de consultar.

## Flujos

### Arranque en frío

1. `mongodb` carga el dataset y `rabbitmq` levanta. `topology-init` declara las colas y termina. Los demás servicios esperan esos pasos y reintentan la conexión.
2. `cleaning-agent` lee la marca de limpieza, no la encuentra y comienza a limpiar, registrando la auditoría.
3. `recommender` se suscribe a `data.cleaned`, lee la marca, ve que no es `done` y espera.
4. El `frontend` recibe `cleaning`: muestra el catálogo con el aviso, sin recomendaciones ni votos.
5. `cleaning-agent` termina, guarda la marca `done` y publica `data.cleaned`.
6. `recommender` recibe el evento y entrena o indexa. El estado pasa a `indexing`.
7. `recommender` termina y su `/health` responde listo. El estado pasa a `ready`.
8. El `frontend` ve `ready`, habilita todas las funciones y deja de consultar.

### Segundo arranque

1. `cleaning-agent` lee la marca `done` y no ejecuta la limpieza.
2. `recommender` lee la marca `done` y prepara el modelo sin esperar ningún evento.
3. `GET /status` responde `ready` en cuanto `recommender` termina de cargar.

La caída de `recommender` o de `backend` se recupera por este mismo camino, con `restart: unless-stopped`. `recommender` se suscribe a la cola antes de leer la marca, para no perder la señal si la limpieza termina entre ambos pasos.

### Voto con reseña

1. El `frontend` envía usuario, película, estrellas y texto al `backend`.
2. El `backend` valida el formato y que el estado sea `ready`; si no lo es, rechaza la petición.
3. El `backend` publica el mensaje en `interactions` y responde "aceptado" sin esperar a MongoDB.
4. `ingest-consumer` toma el mensaje y lo guarda, reemplazando el voto previo del mismo usuario para esa película. Recién entonces confirma el mensaje.
5. Si falla al guardar, el mensaje se deriva a una cola de errores en lugar de perderse.

La reseña no aparece al instante en la ficha: el `frontend` la muestra como enviada hasta la próxima lectura.

### Recomendaciones

1. El `frontend` pide "Recomendadas para vos" o "Películas similares" al `backend`.
2. El `backend` solicita los identificadores a `recommender`, que los obtiene de estructuras ya calculadas en memoria.
3. El `backend` completa los datos de cada película desde MongoDB y responde.

Ninguna petición reentrena el modelo ni calcula similitudes contra todo el catálogo.

## Pendiente

Decisiones abiertas:

- **LLM:** se asume API externa con API key, a confirmar con la cátedra. Si pasa a ser un modelo local, se agrega un contenedor `ollama` y se elimina `egress-net`.
- **Algoritmo del recomendador**, y si el modelo se guarda en un volumen para que el segundo arranque tarde pocos segundos.
- **Lectura de datos sucios:** cómo tolera el `backend` los formatos corruptos mientras dura la limpieza.
- **Caída de `cleaning-agent` a mitad de la limpieza:** el proceso debe poder repetirse o retomarse sin duplicar la auditoría.
- **API key del LLM para la evaluación:** cómo la obtiene la cátedra (key propia, una key del grupo con límite de gasto, o modelo local).

Secciones a completar con la implementación:

- Estrategia de limpieza y uso del LLM en `cleaning-agent`.
- Ruta `/audit`: métricas macro y detalle de registros.
- Estrategia del motor de recomendaciones y justificación del modelo.
- Integraciones con LLM en la interfaz (traducción, chat).
