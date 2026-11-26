# DCIC-Flix26

Plataforma web de catálogo cinematográfico con microservicios, agente de limpieza de datos y motor de recomendaciones, orquestada con Docker Compose.

Proyecto final de Tópicos Avanzados de Desarrollo Web (DCIC, UNS), edición 2026.

> **Estado del documento:** describe el diseño de arquitectura acordado por el grupo. La implementación está en curso: el esqueleto de contenedores sigue el plan de [docs/esqueleto-contenedores.md](docs/esqueleto-contenedores.md). Las secciones que dependen de la funcionalidad están listadas en [Pendiente](#pendiente).

## Ejecución

```bash
docker compose up --build
```

No requiere pasos manuales: la carga del dataset, la declaración de colas, la limpieza y el entrenamiento inicial se coordinan entre los contenedores.

La aplicación queda en **http://localhost:8080** (el puerto se cambia con `FRONTEND_PORT` en `.env`). Por ahora muestra el catálogo con búsqueda por título (`/api/movies`) y, arriba, un aviso mientras se limpian los datos o se preparan las recomendaciones (`/api/status`).

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
pytest -m slow                              # persistencia y reconexión: baja y levanta el sistema (~7 min)
pytest services/recommender                 # tests unitarios del recommender, aparte (ver abajo)
pytest services/backend                     # tests unitarios del backend, aparte
```

Los tests del `recommender` corren en una invocación aparte, con su propio `pytest.ini`: él y el `cleaning-agent` tienen un paquete `app`, y en un mismo proceso de pytest solo se puede importar uno.

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
| `backend` | `mongodb` | Lectura; escribe solo `users` | Catálogo, reseñas, auditoría, marca de limpieza, usuarios |
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
| Marca de limpieza | MongoDB, colección `cleaning`, documento `_id: "state"`, campo `status` (persiste en el volumen) | `pending` (o sin documento), `running`, `done` | Duradera: sobrevive a reinicios. |
| Salud del recomendador | `GET /health` de `recommender` | listo o no | Del proceso: se recalcula en cada arranque. |

El `backend` las combina en `GET /status`:

| Estado | Condición | Efecto en el `frontend` |
| :--- | :--- | :--- |
| `cleaning` | Marca de limpieza distinta de `done` | Catálogo navegable con aviso; recomendaciones y votos deshabilitados. |
| `indexing` | Marca `done`, recomendador no listo | Igual que `cleaning`, con el mensaje correspondiente. |
| `ready` | Marca `done`, recomendador listo | Todas las funciones habilitadas. |

Los eventos disparan trabajo entre servicios; `GET /status` responde siempre a partir del estado real. Por eso un reinicio del `backend` o del `recommender` no deja el sistema en un estado inconsistente.

El `frontend` consulta `GET /status` cada pocos segundos mientras el estado no sea `ready`, y luego deja de consultar.

Respuesta de `GET /status` (en el `frontend`, `/api/status`):

- `200 {"state": "cleaning" | "indexing" | "ready"}`.
- `503 {"detail": "..."}` si no puede leer la marca (Mongo no responde). No responde `cleaning`: sería informar un estado que no conoce.

Que el recomendador esté listo sale del campo `ready` de su `/health`, no del código HTTP: mientras embebe o indexa responde 200 (está sano, pero no listo). El `backend` lo anota en el chequeo que ya hace cada 10 s para su propio `/health`, así el costo de `/status` no depende de cuántos navegadores consulten. El paso a `ready` puede verse hasta 10 s tarde.

Un 503 del `recommender` (perdió Mongo o RabbitMQ) cuenta como no listo, aunque conserve el índice en memoria. Como los dos chequean cada 10 s por separado, después de una caída breve el estado puede quedar en `indexing` entre 10 y 20 s más. Es a propósito: se prefiere informar que no está listo de más y no de menos.

Si el `recommender` se cae después de `ready`, el estado vuelve a `indexing`, pero el `frontend` ya no consulta. El `backend` igual rechaza votos y recomendaciones; cuando una de esas acciones falla por el estado, el `frontend` vuelve a consultar `/status` hasta recuperar `ready` (se implementa con esas funciones).

### Catálogo

La consigna pide que el catálogo se pueda recorrer en todo momento, también mientras se limpia. En ese rato `movies` tiene los datos crudos (años y géneros como texto, duplicados, sin `deleted`) y el `cleaning-agent` los va reemplazando.

**Criterio: el `backend` valida, no corrige.** Cada campo se devuelve solo si cumple lo que garantiza el contrato limpio ([ANOMALIAS.md](analysis/ANOMALIAS.md), sección 7); si no, sale `null` y el `frontend` no lo muestra. Corregir es trabajo del `cleaning-agent`: repetir sus reglas en el `backend` sería mantenerlas en dos lugares para cubrir los segundos que dura la limpieza. Mientras tanto pueden verse duplicados o datos faltantes; al terminar, el catálogo muestra los datos limpios sin hacer nada.

- Se filtra con `deleted != true` y no con `deleted: false`: los documentos crudos todavía no tienen el campo.
- Se ordena de más a menos votada en IMDb. Los votos que no son número (en el crudo, `"1,208"`) cuentan como desconocidos y van al final: si no, Mongo los ordenaría primero. El `_id` desempata, para que ninguna película se repita o falte entre páginas.
- La búsqueda reemplaza los caracteres no ASCII de la consulta por `è`, como hizo la fuente con los títulos (A13): "Amélie" encuentra "Amèlie".
- Las carátulas que no cargan (≈12 %) se reemplazan en el `frontend` por una genérica con el título.

`GET /movies` (en el `frontend`, `/api/movies`):

- Parámetros: `q` (texto del título, hasta 100 caracteres; opcional) y `page` (desde 1). Fuera de rango: 422.
- `200 {"items": [{"id", "title", "year", "poster", "genres", "imdbRating"}], "page", "pageSize": 24, "total"}`. Una página más allá del final trae `items` vacío.
- `503 {"detail": "..."}` si Mongo no responde.

La búsqueda y la página viven en la URL del `frontend` (`/?q=…&page=3`): al volver de una ficha, el catálogo queda donde estaba.

### Ficha

Cada película tiene su página en `/movies/{id}`, con sus datos, la sinopsis y las reseñas. Como el catálogo, se puede ver en todo momento y sigue el mismo criterio: **el `backend` valida, no corrige**.

- **Copias duplicadas:** si el id es de una copia descartada en la fusión (A5), el `backend` devuelve la película ganadora (`mergedInto`), con su id, y el `frontend` corrige la URL. Así, un link guardado antes de la limpieza sigue funcionando. El contrato garantiza que `mergedInto` apunta a una película activa: se sigue un solo salto.
- **Reseñas durante la limpieza:** se muestran las crudas, validadas. Pueden verse comentarios basura, anónimas o votos repetidos hasta que termine; el aviso de estado lo explica.
- **Reseñas incompletas:** el soft delete es lo único que saca una reseña. `commentHidden` oculta solo el texto (quedan nombre, estrellas y fecha), y `rating: null` (sin LLM) solo las estrellas ("Sin puntaje").
- **Total:** sale del conteo de reseñas activas, no de `num_mflix_comments`, que no cuenta las de comentario oculto.
- **Nombre:** las reseñas del dataset lo traen. Las que crea el `ingest-consumer` tienen solo `user_id`, y el nombre se busca en `users`: una consulta para todas, y ninguna si no hay de esas.
- **Privacidad:** la API no devuelve `user_email`.
- **Reseña propia:** cada reseña trae `userId`, porque los nombres se repiten (hay 136 casos de dos o más reseñas activas de una película con el mismo nombre). Las anónimas (B4) traen `null`.

`GET /movies/{id}` (en el `frontend`, `/api/movies/{id}`):

- `200` con los campos del catálogo más `plot` (`fullplot` si existe, si no `plot`), `runtime` (minutos), `rated`, `directors`, `cast`, `countries`, `languages`, `imdbVotes` y `awards` (texto). Lo que no cumple el contrato sale `null` o lista vacía. El `id` puede no ser el pedido (copia fusionada).
- `404 {"detail": "..."}` si el id no es válido o no existe.
- `503 {"detail": "..."}` si Mongo no responde.

`GET /movies/{id}/reviews` (en el `frontend`, `/api/movies/{id}/reviews`):

- `200 {"items": [{"id", "userId", "userName", "rating", "comment", "date", "datePrecision"}], "total"}`. Las activas, de la más reciente a la más vieja; sin fecha válida, al final. Hasta 100 (hoy el máximo es 55 por película); `total` cuenta todas. `date` es ISO en UTC; con `datePrecision: "year"` (las `circa`) se muestra solo el año.
- No comprueba que la película exista: un id que no es de ninguna da `items` vacío.
- `404` si el id no es válido; `503` si Mongo no responde.

### Usuarios

No hay registro: en el `frontend` se elige un usuario de la lista. Son los 2.000 del dataset, que solo figuran repetidos en cada reseña, y 5 nuevos (`usr_2001` a `usr_2005`) sin ningún voto, para probar el arranque en frío del recomendador.

La colección `users` la carga el `backend` cada vez que arranca: `{_id, name, email, preloaded}`, con el `user_id` como `_id`.

- **Por qué al arrancar el `backend`:** es automático, sirve también con un volumen ya cargado y no agrega un contenedor para un trabajo de menos de un segundo. Descartados: un servicio aparte; un endpoint, que alguien tendría que llamar; un script en `dataset/`, que solo corre con el volumen vacío y es la carpeta de la cátedra; y el `cleaning-agent`, que no corre si la base ya está limpia.
- **Idempotente:** agrega los usuarios que faltan y no toca los que están. Por eso completa una carga cortada a la mitad y admite dos `backend` a la vez.
- **No espera a la limpieza:** en el crudo, cada `user_id` tiene un solo nombre y un solo email. Solo se saltean las reseñas anónimas (B4), por id, y las del `ingest-consumer`, que no tienen nombre.
- **Si Mongo no responde,** reintenta cada 5 s. El resto del `backend` no espera.
- **Privacidad:** el email sirve para buscar, pero la API no lo devuelve. Los nombres se repiten (432 los comparten varios usuarios): lo que distingue a dos usuarios es el id.

`GET /users` (en el `frontend`, `/api/users`):

- Parámetro: `q` (texto contenido en el nombre, el email o el id, hasta 100 caracteres; opcional). Más largo: 422.
- `200 {"items": [{"id", "name", "preloaded"}], "total"}`. Hasta 20, con los nuevos (`preloaded`) primero y después por nombre; `total` cuenta todos los que coinciden.
- `503 {"detail": "..."}` si los usuarios todavía se están cargando o Mongo no responde.

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

### Caída de `cleaning-agent` a mitad de la limpieza

1. Antes de escribir nada, `cleaning-agent` copia `movies` y `reviews` a `moviesRaw` y `reviewsRaw`, y cada corrida lee de esa copia.
2. Si se cae (o falla al escribir), termina con código 1 y `restart: unless-stopped` lo levanta. Encuentra la marca en `running` y **repite la limpieza completa** desde la copia: los documentos y la auditoría se reemplazan por `_id`, sin duplicarse.
3. Si se cae entre guardar `done` y publicar `data.cleaned`, la marca lo indica (`eventPublished: false`) y publica al arrancar. El evento puede llegar repetido, nunca perderse: el `recommender` lo tolera porque reindexa desde la base.

El detalle y las alternativas descartadas están en [ANOMALIAS.md](analysis/ANOMALIAS.md), sección 7.

### Voto con reseña

1. El `frontend` envía usuario, película, estrellas y texto al `backend`.
2. El `backend` comprueba el formato, que el estado sea `ready` y que existan el usuario y la película; si no, rechaza la petición.
3. El `backend` publica el mensaje en `interactions`, con solo el `user_id` del usuario. Cuando RabbitMQ confirma que lo recibió, responde "aceptado", sin esperar a que se guarde en MongoDB.
4. `ingest-consumer` toma el mensaje, lo guarda reemplazando el voto previo del mismo usuario para esa película y actualiza el contador de reseñas. Recién entonces confirma el mensaje.
5. Si el mensaje no se puede guardar (formato inválido, película inexistente o un error inesperado), se deriva a `interactions.errors` y la cola sigue. Si el problema es que MongoDB no responde, el mensaje espera y se reintenta.

RabbitMQ puede entregar el mismo voto más de una vez, por ejemplo si el consumer se cae entre guardar y confirmar. Guardarlo otra vez no cambia nada. Las decisiones y las pruebas de fallas están en [docs/ingest-consumer.md](docs/ingest-consumer.md).

La reseña no aparece al instante en la ficha: el `frontend` la muestra como enviada hasta la próxima lectura.

`POST /movies/{id}/reviews` (en el `frontend`, `/api/movies/{id}/reviews`), con `{"userId", "rating", "comment"}` (`comment` es opcional):

| Código | Cuándo | Qué hace el `frontend` |
| :--- | :--- | :--- |
| `202 {"movieId", "userId", "rating", "comment", "votedAt"}` | Aceptado: no se va a perder, aunque todavía no esté guardado | La muestra como enviada |
| `422` | Formato inválido | Muestra el error |
| `404` | No existe el usuario o la película, o la película no está activa | Muestra el error |
| `409` | El estado no es `ready` | Vuelve a consultar `/status` |
| `503` | Mongo o RabbitMQ no responden, o los usuarios se están cargando | Ofrece reintentar |

- El 409 distingue "el sistema funciona, pero todavía no se puede votar" de una caída (503).
- Ante un 503, reintentar es seguro: si el voto había llegado, el nuevo lo reemplaza.
- La hora la pone el `backend`; si el cuerpo trae `votedAt`, se ignora.
- Un JSON mal formado da 400 o 422 con `detail` como lista, y un cuerpo de más de 1 MB, 413 en HTML (nginx): conviene guiarse por el código.

Por qué se comprueba antes y qué se delega está en [docs/ingest-consumer.md](docs/ingest-consumer.md), sección 8.

### Recomendaciones

1. El `frontend` pide "Recomendadas para vos" o "Películas similares" al `backend`.
2. El `backend` solicita los identificadores a `recommender`, que los obtiene de estructuras ya calculadas en memoria.
3. El `backend` completa los datos de cada película desde MongoDB y responde.

Ninguna petición reentrena el modelo ni calcula similitudes contra todo el catálogo.

El `recommender` expone `GET /users/{user_id}/recommendations`, `GET /movies/{movie_id}/similar`, `GET /rankings` y `GET /genres`, todos solo en `internal-net`. Mientras no termina de indexar responden 503. El detalle está en [docs/recomendador.md](docs/recomendador.md), sección 9.4.

## Limpieza de datos

El `cleaning-agent` limpia el dataset una sola vez, en el primer arranque. El detalle de cada anomalía, sus números y el contrato del esquema limpio están en [analysis/ANOMALIAS.md](analysis/ANOMALIAS.md).

- **Criterio:** se corrige solo lo que se recupera sin adivinar, con código determinista antes que con un LLM. Lo que no se puede recuperar queda en `null` ("no se sabe").
- **Cómo:** copia `movies` y `reviews` a `moviesRaw` y `reviewsRaw`, lee de esa copia y limpia en memoria con funciones puras de Python. Primero aplica las reglas de campo y después las que cruzan documentos: fusión de películas duplicadas, reasignación de reseñas, votos duplicados y contadores. Después reemplaza cada documento por `_id`. Contra Mongo tarda ≈12 s desde cero.
- **Nada se borra:** los descartes son soft delete (`deleted: true` y `deletedReason`). Todo servicio que lee filtra `{ deleted: false }`.
- **Auditoría:** un registro por documento en `audit`, con campo, regla, valor original y valor nuevo de cada cambio. Es lo que muestra `/audit`.
- **Caídas:** si se cae a mitad, repite todo desde el crudo, porque correr la limpieza dos veces da lo mismo que una. `data.cleaned` sale al menos una vez.
- **Sin LLM:** las reseñas cuyo rating no se recupera del texto quedan con `rating: null` (1.884). El contrato lo admite mientras el LLM esté en pausa.

## Pendiente

Decisiones abiertas:

- **LLM:** se asume API externa con API key, a confirmar con la cátedra. Si pasa a ser un modelo local, se agrega un contenedor `ollama` y se elimina `egress-net`.
- **API key del LLM para la evaluación:** cómo la obtiene la cátedra (key propia, una key del grupo con límite de gasto, o modelo local).

Para el `frontend`:

- **Selector de usuario y formulario de voto.** Las API están (secciones "Usuarios", "Ficha" y "Voto con reseña").

Secciones a completar con la implementación:

- Uso del LLM en `cleaning-agent` (en pausa hasta definir el proveedor).
- Ruta `/audit`: métricas macro y detalle de registros.
- Estrategia del motor de recomendaciones y justificación del modelo: está completa en [docs/recomendador.md](docs/recomendador.md), con la implementación en la sección 9.6. Falta resumirla acá.
- Integraciones con LLM en la interfaz (traducción, chat).
