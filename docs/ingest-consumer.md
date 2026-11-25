# Ingesta de votos

> **Estado: implementado en [services/ingest-consumer](../services/ingest-consumer/) (2026-11-23).** El `backend` publica los votos desde el 2026-11-25 (sección 8).

El `ingest-consumer` toma los votos con reseña que el `backend` deja en la cola `interactions` y los guarda en MongoDB. Su garantía es que **un voto aceptado no se pierde ni se guarda dos veces**.

```
frontend ──POST voto──▶ backend ──publica──▶ [interactions] ──▶ ingest-consumer ──▶ mongodb
              ◀─"aceptado"─┘                       │                   │ (1) guarda
                                                   │◀──── (2) ack ─────┘
                                                   └─ si no se puede guardar ─▶ [interactions.errors]
```

**Por qué una cola y no escribir directo en Mongo:**

- El usuario no espera a que Mongo guarde.
- Con el consumer o Mongo caídos, los votos se acumulan y se procesan al volver.
- Hay un solo escritor de votos, de a un mensaje por vez: dos votos del mismo usuario no compiten.

El costo es la consistencia eventual: la reseña no aparece al instante en la ficha.

## 1. Decisiones

| # | Tema | Decisión | Alternativa descartada |
| :-- | :-- | :-- | :-- |
| I1 | Datos del usuario en el mensaje | Solo `user_id`; el nombre y el email los resuelve el `backend` al leer (colección `users`, [README](../README.md#usuarios)) | Mandarlos en cada mensaje: copias de un dato que no es del voto, y el email circulando por la cola |
| I2 | Volver a votar | Se actualiza el mismo documento. Es una sola escritura, atómica | Crear otro y descartar el viejo: son dos escrituras, y una caída entre ambas deja dos votos activos o ninguno |
| I3 | `num_mflix_comments` | Se recuenta en cada voto | Sumar 1: una reentrega cuenta doble |
| I4 | Un solo voto activo por usuario y película | Índice único parcial en Mongo | Confiar en el código |
| I5 | Voto más viejo que el guardado | No lo pisa: se compara `votedAt` | El último en llegar gana |
| I6 | Mongo no responde | Se reintenta sin responderle a RabbitMQ | Derivar a errores: una caída de 30 s mandaría ahí votos buenos |
| I7 | Error inesperado con un mensaje (un bug) | A `interactions.errors`, con el error en el log | Terminar el proceso: RabbitMQ reentrega el mismo mensaje y un voto frena la cola para siempre |
| I8 | Comentarios cortos | Se muestran. Solo se oculta (`commentHidden`) el texto vacío | Aplicar B7 de [ANOMALIAS](../analysis/ANOMALIAS.md): oculta todo lo de menos de 3 palabras, como "Muy buena". Esa regla se eligió por un hueco en los datos del dataset |

## 2. Mensaje

Está definido en [interactions.py](../libs/common/dcicflix_common/interactions.py), que usan el `backend` (`encode`) y el consumer (`decode`): con las dos puntas en un archivo, el formato no puede divergir.

```json
{"user_id": "usr_0142", "movie_id": "573a1393f29313caabcdd7d8",
 "rating": 5, "comment": "Great movie", "votedAt": "2026-11-23T18:04:05.123Z"}
```

| Campo | Se acepta |
| :-- | :-- |
| `user_id` | Texto no vacío, sin espacios alrededor y distinto de `usr_0000` (B4) |
| `movie_id` | 24 dígitos hexadecimales en minúscula |
| `rating` | Entero de 1 a 5. Se rechazan `"5"`, `5.0` y `true` (en Python, `True == 1`) |
| `comment` | Texto de hasta 5.000 caracteres; puede ser `""`. El más largo del dataset tiene 254 |
| `votedAt` | Fecha ISO 8601 con zona horaria. Es la hora del voto según el `backend`, no la del navegador ni la del procesamiento |

La validación está en el constructor de `Interaction`, así que un objeto inválido no puede existir en ninguna de las dos puntas. Los campos desconocidos se ignoran.

**Cualquier problema de contenido es `InvalidInteraction`.** Si alguno lanzara otra cosa y matara al proceso, RabbitMQ reentregaría ese mensaje para siempre. Un caso sutil es medio emoji (`\ud83d`): es JSON válido, pero Mongo lo rechaza.

**La fecha se trunca a milisegundos**, la precisión de Mongo. Si no, un voto reentregado parecería posterior a sí mismo ya guardado.

## 3. Guardar ([store.py](../services/ingest-consumer/ingest/store.py))

1. **La película tiene que existir y estar activa.** Si no, `InvalidInteraction`.
2. **Upsert de la reseña**, en una sola operación. El filtro busca el voto activo del usuario para esa película, siempre que no sea más nuevo:

   | Situación | Qué pasa |
   | :-- | :-- |
   | No había voto | No encuentra nada y lo crea |
   | Había uno más viejo, sin fecha, o es el mismo reentregado | Lo actualiza |
   | Había uno más nuevo | No lo encuentra, intenta crear otro y el índice único lo impide: queda el que estaba |

3. **Recontar** las reseñas visibles de la película, con el mismo criterio que la limpieza (A16). Se hace aunque el voto sea viejo, porque una entrega anterior pudo caerse justo antes de este paso.

**Cuándo hay un voto más nuevo:** con un solo consumer casi nunca. Puede pasar si dos peticiones casi simultáneas se publican en orden inverso, o si alguien reencola un mensaje de `interactions.errors`.

**Índice `one_active_vote`:** único sobre `(user_id, movie_id)` y parcial sobre `deleted: false`, porque los votos que descartó la limpieza sí se repiten. Lo crea el consumer al arrancar. No hace falta esperar a la limpieza: los documentos crudos no tienen `deleted` y quedan afuera. Comprobado: la limpieza completa, y repetida, con el índice puesto da las mismas 60.206 reseñas activas.

**`j: true`:** Mongo responde con la escritura ya en el journal, en disco. Sin eso, un corte podría perder un voto que ya se le confirmó a RabbitMQ.

**Qué queda en la reseña:** las nuevas no tienen `user_name` ni `user_email`. Las del dataset que se vuelven a votar conservan los suyos, y el registro de `audit` de la limpieza sigue describiendo el valor original.

## 4. Consumir ([consumer.py](../services/ingest-consumer/ingest/consumer.py))

RabbitMQ entrega un mensaje por vez (`prefetch=1`) y no lo borra hasta recibir una respuesta:

| Resultado | Respuesta |
| :-- | :-- |
| Guardado, o ya había uno más nuevo | `ack` |
| Mensaje inválido | `reject`: pasa a `interactions.errors` |
| Error inesperado | `reject`, con el error en el log |
| Mongo no responde | Ninguna: se reintenta en la próxima vuelta |
| Mongo rechaza la operación (por ejemplo, credenciales) | Ninguna: el proceso termina (D14) y el mensaje sigue en la cola. No es culpa del mensaje, y derivarlo mandaría todos los votos a errores |

- **El callback solo anota el mensaje; lo procesa el `tick`.** Así, mientras Mongo no responde, el bucle del worker sigue atendiendo la conexión, que RabbitMQ corta si nadie la atiende.
- **Tope de 10 s para guardar.** Sin él, un Mongo colgado, que acepta la conexión y no contesta, bloquearía ese bucle.
- **La suscripción se hace en `on_connect`**, en cada conexión, porque muere con ella. Si no, al reconectar el servicio quedaría *healthy* sin recibir votos.
- **Si el broker cancela la suscripción o cierra el canal**, el proceso termina y Docker lo reinicia, por el mismo motivo.

## 5. Fallas probadas (2026-11-23)

Con los contenedores reales. En todas, el voto en curso quedó guardado **una sola vez**, el contador subió exactamente 1 y `interactions.errors` quedó vacía.

| Falla | Comportamiento | Reinicios |
| :-- | :-- | :-- |
| Mongo detenido 45 s | El voto espera y se guarda ≈ 5 s después de que vuelve | 0 |
| Mongo congelado 75 s (`docker pause`) | Alterna intento y corte a los 10 s; RabbitMQ no corta la conexión. Se guarda ≈ 4 s después | 0 |
| Muere entre guardar y el `ack` | RabbitMQ reentrega y el resultado no cambia | — |
| RabbitMQ detenido con un voto a medio guardar | Se guarda, reconecta y la reentrega no lo duplica | 0 |
| RabbitMQ reiniciado con Mongo detenido | El mensaje sobrevive y se guarda al volver Mongo | 0 |
| Cola borrada | Termina y se reinicia hasta que `topology-init` corre de nuevo | 3 |
| Cola borrada y recreada al instante | Lo nota por la cancelación (la verificación cada 10 s no lo vería) y se suscribe de nuevo en ≈ 3 s | 1 |
| Mongo caído más que el plazo de RabbitMQ para responder un mensaje (30 min; probado bajándolo a 20 s) | RabbitMQ cierra el canal, el consumer se reinicia y espera a Mongo antes de suscribirse. El voto vuelve a la cola | 1 |

**Medido en Docker** (Windows, Docker Desktop):

| Qué | Valor |
| :-- | :-- |
| Guardar un voto | Mediana 69 ms, p95 185 ms |
| 200 votos seguidos por la cola | 16 s, ≈ 12 por segundo |
| Crear el índice sobre la base limpia | 1,25 s; 1 ms si ya existe |

## 6. Tests

| Dónde | Qué prueba | Necesita |
| :-- | :-- | :-- |
| [test_interactions.py](../libs/common/tests/test_interactions.py) | El formato del mensaje | Nada |
| [test_ingest_consumer.py](../services/ingest-consumer/tests/test_ingest_consumer.py) | Qué se responde según el resultado | `pymongo` |
| [test_ingest_store.py](../services/ingest-consumer/tests/test_ingest_store.py) | Guardar, reemplazar, reentregas e índice | Docker (Mongo descartable) |
| [test_ingest.py](../tests/architecture/test_ingest.py) | De la cola a Mongo | El sistema levantado |
| [test_resiliencia.py](../tests/architecture/test_resiliencia.py) (`slow`) | Mongo detenido, y morir entre guardar y el `ack` | El sistema levantado |
| [test_vote_api.py](../tests/architecture/test_vote_api.py) | De la API a la ficha, y los rechazos | El sistema levantado |
| [test_resiliencia.py](../tests/architecture/test_resiliencia.py) (`slow`) | Votar por la API sin consumer, Mongo, RabbitMQ o `recommender` | El sistema levantado |
| [test_votes.py](../services/backend/tests/test_votes.py) y [test_publisher.py](../services/backend/tests/test_publisher.py) | El `backend`: comprobaciones y publicación | Docker (Mongo descartable) |

Los votos de prueba usan un usuario nuevo y se borran al terminar. Se comprobó que los tests fallan si el servicio está mal: se introdujeron más de 40 errores en el código y todos se detectaron, salvo uno que solo cambia el texto de un log.

## 7. Límites

- **Una cola borrada pierde los mensajes que tenía.** Borrarla es una acción manual.
- **`interactions.errors` se revisa a mano:** nada la consume. El motivo de cada mensaje está en el log del consumer.
- **Un `votedAt` adelantado bloquea los votos siguientes** de ese usuario para esa película, hasta que pase esa hora (I5). Por eso la hora la pone el `backend`.
- **Sin probar con contenedores:** el error inesperado y que Mongo rechace la operación (solo con tests unitarios), y un corte brusco de Mongo, que es lo que cubre `j: true`.

## 8. Publicar el voto (`backend`)

La API está en el [README](../README.md#voto-con-reseña); el código, en [votes.py](../services/backend/app/votes.py) y [publisher.py](../services/backend/app/publisher.py).

| # | Tema | Decisión | Alternativa descartada |
| :-- | :-- | :-- | :-- |
| V1 | Usuario y película inexistentes | Se comprueban antes de publicar | Delegarlo a la cola |
| V2 | El estado no es `ready` | 409 | 503: no se distinguiría de una caída |
| V3 | Voto a una copia fusionada | 404, por V1. Solo pasa con una ficha abierta desde antes de la limpieza; al recargar lleva a la ganadora | Pasarlo a la ganadora: código para un caso muy raro |
| V4 | Cuándo se responde 202 | Con la confirmación de RabbitMQ. Desconectado, error al instante; colgado, a los 2 s | No esperarla: con RabbitMQ caído se aceptaría un voto que se pierde |
| V5 | Canal | Uno por voto: si se rompe, el siguiente no se entera | Uno compartido: hay que detectar el cierre y reabrirlo |

**Qué se delega y qué no.** Comprobar el usuario y la película son dos lecturas por `_id`, ≈ 1,4 ms cada una. Lo lento es guardar: ≈ 69 ms, porque Mongo escribe en disco (`j: true`) la reseña y el contador. Eso es lo que va a la cola. Delegar también la comprobación no ahorra trabajo, y después del 202 no hay forma de avisarle a quien vota, salvo que pregunte por el resultado: más carga que la que se ahorró.

`interactions.errors` queda para lo que el usuario no puede arreglar, como un error nuestro: el mensaje no se pierde y la cola sigue.

El consumer comprueba la película pero no el usuario: sin V1, un voto de un usuario inexistente se guardaría como una reseña sin nombre.

**Detalles de la publicación:**

- **`on_return_raises`:** sin él, aio-pika da por bueno publicar en una cola que no existe.
- **Mensaje persistente:** que la cola sea durable no alcanza; sin esto, vuelve vacía de un reinicio.
- **`asyncio.wait` y no `wait_for`:** con RabbitMQ colgado, cerrar el canal también se cuelga, y `wait_for` esperaría a que termine.

**Fallas probadas (2026-11-25)** con los contenedores reales. Las de RabbitMQ congelado y reiniciado, publicando un voto por segundo en una cola temporal; las de servicios detenidos, votando por la API:

| Caso | Resultado |
| :-- | :-- |
| Normal, con confirmación | 7 a 8 ms |
| 100 votos a la vez | 100 aceptados en 249 ms |
| Cola inexistente | Error en 7 ms |
| RabbitMQ congelado 8 s (`docker pause`) | Error a los 2 s. 15 aceptados, 15 en la cola |
| RabbitMQ reiniciado | Error al instante hasta reconectar (≈ 15 s). 30 aceptados, 30 en la cola |
| Consumer detenido | Se acepta; el voto se guarda cuando vuelve |
| Mongo detenido | 503 |
| RabbitMQ detenido | 503; cuando el `recommender` también lo nota, el estado pasa a `indexing` y da 409 (README, "Estado del sistema") |
| `recommender` detenido | 409, cuando el `backend` lo nota (hasta 10 s) |

**Límite:** si la respuesta de RabbitMQ no llega a tiempo, el voto pudo haberse publicado y el usuario ve un error. Reintentar es seguro, porque el consumer reemplaza el voto anterior.
