# Usuario y voto en el `frontend`

Cómo se elige el usuario y cómo se vota desde la ficha. Las API están en el [README](../README.md) ("Usuarios", "Ficha" y "Voto con reseña"); lo que hace el `backend` con el voto, en [ingest-consumer.md](ingest-consumer.md), sección 8.

## 1. Piezas

```
App
 └─ StatusProvider         status.tsx    consulta /status en un solo lugar; recheck()
     └─ UserProvider       user.tsx      usuario elegido, en localStorage; abre el selector
         └─ PendingVotesProvider  pending.tsx   votos aceptados y todavía no leídos
             ├─ encabezado        UserPicker.tsx  botón y <dialog> con búsqueda en /users
             ├─ aviso de estado   App.tsx
             └─ ficha             MovieDetail.tsx
                  ├─ VoteAndReviews   lee las reseñas una vez para las dos partes
                  │    ├─ VoteForm    VoteForm.tsx, votes.ts
                  │    └─ Reviews     withOwnVote() en movie.ts: "(vos)" y "Enviada"
                  └─ Similar       películas similares (PR #9); usa el mismo estado
```

El usuario y el estado son de toda la app, no del formulario: de ellos dependen también las recomendaciones.

## 2. Decisiones

| # | Tema | Decisión | Alternativa descartada |
| :-- | :-- | :-- | :-- |
| S1 | Dónde vive el usuario elegido | Contexto de React y `localStorage`. Si cambia en otra pestaña, esta lo sigue | La URL: un link compartido llevaría tu usuario |
| S2 | Forma del selector | `<dialog>` modal: no saca de la pantalla, y Esc, fondo inerte y foco vienen del navegador | Una página `/users` |
| S3 | Sin usuario elegido | Cada pantalla decide; el formulario invita a elegir uno y abre el selector | Uno por defecto: se votaría sin querer en nombre de otro |
| S4 | Después del 202 | No releer. Lo aceptado se muestra como "Enviada", en memoria, hasta que una lectura traiga la reseña con fecha ≥ `votedAt` | Releer cada pocos segundos: pedidos de más por cada voto (como V1 en el `backend`) |
| S5 | Cuándo se puede votar | Solo con `ready`. Si no, el formulario se ve deshabilitado con el motivo. Ante un 409 llama a `recheck()`, conserva lo escrito y se habilita solo | Habilitarlo siempre y rechazar al enviar |
| S6 | 503 o sin respuesta | Conserva lo escrito y el botón ofrece reintentar: el voto nuevo reemplaza al anterior | Reintento automático |
| S7 | Estrellas | Cinco radios: teclado (flechas) y lector de pantalla sin código extra | Botones hechos a mano |
| S8 | Tests | Sin framework en el repo; se probó con Chrome real (sección 3) | Vitest: suma dependencias al `frontend` |

Detalles que salieron al implementar:

- **Un solo estado para toda la app.** Las películas similares (PR #9) habían agregado, en paralelo, un contexto con `recheck()` de la misma forma (`useSystemStatus()` → `{ result, recheck }`). Al mergear quedó una sola implementación, `status.tsx`, que suma el `isReady()` de las similares. Así, un 409 en las similares deshabilita también el formulario, y al revés (comprobado tras el merge).
- **La reseña propia se reconoce por `userId`,** que se agregó a `GET /movies/{id}/reviews`: en 136 casos, una película tiene dos o más reseñas activas con el mismo nombre.
- **El formulario espera a las reseñas** ("Cargando tu voto…"). Si no, arrancaría vacío y el voto anterior llegaría con lo escrito ya cambiado.
- **El foco del selector se pone a mano:** React no deja el atributo `autofocus` en el HTML, y `showModal()` lo llevaría al primer botón.
- **Un 503 de `/users` no dice si los usuarios se están cargando o si Mongo no responde,** así que el mensaje no elige: "todavía no están disponibles".
- **El comentario se corta en 5.000,** como el `backend`. El navegador cuenta unidades UTF-16 y el `backend`, caracteres: el del navegador es el más estricto, así que nunca da 422.

## 3. Pruebas (2026-11-26)

Con Chrome manejado por `puppeteer-core`, contra los contenedores reales, en producción (`:8080`) y, el selector, también en desarrollo (`:5173`, con `StrictMode`). Los votos se hicieron con un usuario temporal, que al final se borra junto con sus votos, y se restaura el contador de la película. Lo que no se puede provocar sin desarmar el sistema se simuló interceptando el pedido (marcado "simulado").

| Caso | Resultado |
| :-- | :-- |
| Arranque desde cero (`down -v`, `up --build`), con una ficha abierta | Limpieza a los 1:57, `indexing` a los 2:38, y el formulario se habilitó solo a los 8:56, sin recargar. El `recommender` tardó 398 s en embeber los plots |
| Buscar "adrian hall" letra por letra | Un solo pedido; los dos Adrian Hall, distinguidos por el id |
| Elegir, recargar, otra pestaña | Persiste, y la otra pestaña lo sigue sin recargar |
| `/users` con 503 (simulado) | Lo dice y "Reintentar" carga la lista |
| Votar | "Enviada" arriba, sin volver a leer las reseñas; al volver a la ficha, la guardada con su fecha |
| `recommender` detenido, con la página creyendo que está listo | 409; se deshabilita con "Estamos preparando las recomendaciones", conserva lo escrito y se habilita solo al volver |
| RabbitMQ congelado | 503: "el servicio no responde", y el botón dice "Reintentar" |
| Usuario inexistente | 404: "no existe el usuario" |
| Sin red, sin respuesta, 422 con `detail` de lista (simulados) | "No sabemos si el voto llegó"; corta a los 8 s; "HTTP 422" |
| `ingest-consumer` detenido | Al navegar, la lectura trae el voto viejo pero sigue "Enviada" con el nuevo; al volver el consumer, se guarda |
| Dos "Hayden Johnson" en la misma película | Solo se marca "(vos)" el del usuario elegido, y el formulario se precarga con su voto |

## 4. Límites

- **"Enviada" no sobrevive a recargar.** Si se recarga antes de que el voto se guarde, se ve el anterior hasta que se guarda. El voto no se pierde.
- **Un voto que el consumer rechaza** (por ejemplo, si la película se descartó entre la comprobación y el guardado) queda como "Enviada" hasta recargar.
- **La ficha no reintenta sola si la película da error** (por ejemplo, 502 mientras arranca el `backend`): hay que apretar "Reintentar". Es anterior a este trabajo.
- **El arranque desde cero tardó entre 9 y 11 minutos** en dos corridas, contra los ≈10 que la cátedra espera (ANOMALIAS, pendiente 4). Lo que más pesa es embeber los plots.
