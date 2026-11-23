# Anomalías del dataset y reglas de limpieza

Resultado del análisis de calidad de las colecciones `movies` (19.842 documentos) y `reviews` (61.488) que entrega la cátedra.
Define **qué** tiene que corregir el `cleaning-agent`, **en qué orden** y **cómo queda** cada campo en la base limpia.

- **Fuente de verdad de los números:** [`dataset_profiling.ipynb`](dataset_profiling.ipynb). Cada anomalía indica la sección del notebook donde se mide. El notebook solo diagnostica: no modifica el dataset.
- **Códigos:** `A` = `movies`, `B` = `reviews`, `G` = general. Se mantienen para poder rastrear cada regla hasta su análisis.
- **Estados:** **decidida**, **propuesta** (falta confirmar) o **abierta** (falta una respuesta del grupo o de la cátedra).
- **Criterio general:** calidad sobre cantidad. Se corrige solo lo que se puede recuperar **sin adivinar**, y se usa código determinista antes que un LLM. Lo que no se puede recuperar queda en `null` ("no se sabe") o se documenta como limitación. Todo cambio deja el valor original en la auditoría.

## 1. Resumen

### `movies`

| # | Campo | Anomalía | Casos | Regla | Estado | Notebook |
| :-- | :-- | :-- | --: | :-- | :-- | :-- |
| A3, A4 | documento | Películas duplicadas | 655 grupos (701 copias sobrantes) | Fusionar en una copia; las demás a soft delete | decidida | 2.1, 2.7 |
| P1 | `year` | Texto, `è`, `circa`, negativos, `null` | 434 + 90 negativos | Rescatar el número; `null` si no hay | decidida | 2.2 |
| P2 | `runtime` | Texto (`'1h 25m'`, `'100 min'`), negativos, `null` | 255 + 78 negativos | Convertir a minutos; negativos con `abs` | decidida | 2.3 |
| P3 | `genres` | Texto en vez de lista; espacios sobrantes | 378 textos, 614 elementos | Partir y recortar | decidida | 2.4 |
| A12, A15, P5 | `imdb.rating` | Centinelas, escala ×10, texto | 136 + 132 + 135 | Centinelas → `null`; ×10 → ÷10; texto → número | decidida | 2.5 |
| A14 | `imdb.votes` | Texto con comas; vacíos | 405 + 19 | Número; vacíos → `null` | decidida | 2.5, 4.2 |
| P4 | `title` | Espacios al inicio o al final | 417 | Recortar | decidida | 2.6 |
| A13 | texto | Caracteres no ASCII reemplazados por `è` | 4.933 películas | No se corrige: limitación de la fuente | decidida | 4.1 |
| A16 | `num_mflix_comments` | No coincide con las reseñas reales | 10.806 de 13.255 | Recalcular al final | decidida | 4.3 |
| A17 | `writers` | Nombres cortados por comas | 46 películas | Volver a unir los pedazos | decidida | 4.4 |
| A18 | `writers`, `cast`, `directors` | Elementos repetidos | 130 listas | Quitar los idénticos | decidida | 4.5 |
| A19 | `released` | Año distinto de `year` | 1.060 | No se corrige: es otra fecha | decidida | 4.6 |
| A20 | `rated` | Mayúsculas y sinónimos | ~700 | Mayúsculas; `UNRATED` → `NOT RATED` | decidida | 4.7 |
| A21, A22 | `lastupdated` | Texto en 2 formatos | 19.842 | Guardar como `Date`; no se modifica | decidida | 4.8 |
| A23, A24 | `poster` | Servidor viejo; imágenes borradas | 1; ≈12 % | Cambiar servidor; rotos → frontend | decidida | 4.9 |
| A25 | `awards` | Números mal sumados | 2.577 | Recalcular desde `awards.text` | decidida | 4.10 |
| A26, A27 | `tomatoes` | `critic` incompleto; `dvd` imposibles | 296; 330 | No se corrige: se documenta | decidida | 4.11, 4.12 |

### `reviews`

| # | Campo | Anomalía | Casos | Regla | Estado | Notebook |
| :-- | :-- | :-- | --: | :-- | :-- | :-- |
| B4 | `user_id` | Vacío o `usr_0000` (anónimas) | 459 | Soft delete | decidida | 3.6 |
| B11 | `movie_id` | Apunta a una película inexistente | 350 | Soft delete | decidida | 3.3 |
| B5, B6, B14 | `rating` | Fuera de 1–5, `null`, texto | 1.211 + 928 + 873 | Texto → número; inválidos → regex "N stars" → LLM | decidida | 3.5, 3.7, 5.3 |
| B7, B8 | `comment` | Basura o sin contenido | 1.583 | Ocultar el comentario; el voto se queda | decidida | 3.1 |
| B12 | — | Sin rating válido ni comentario útil | 0 | Soft delete | decidida | 5.3 |
| B2, B9, B10 | `date` | Formatos mezclados, `yesterday`, `circa`, futuras | 910 + 30 | Normalizar; lo imposible → `null` | decidida | 3.2 |
| B1, B13 | — | Votos duplicados del mismo usuario | 472 pares | Gana el voto válido más reciente | decidida | 3.4, 5.2 |
| G2 | `movie_id` | Apunta a una copia duplicada que se descarta | 2.474 | Reasignar a la copia ganadora | decidida | 5.1 |

## 2. Orden de aplicación

El orden importa: varias reglas usan el resultado de otras (A8).

1. **Limpiar campos** de cada documento (P1–P5, A12, A14, A15, A17, A18, A20, A21, A23, A25 en `movies`; B2, B5, B6, B9, B10, B14 en `reviews`). Va primero porque si se fusiona antes, un `'1971è'` cuenta como "presente" y gana sobre un `1971` limpio.
   - A14 antes que A15: primero se sabe qué `imdb.votes` quedan en `null`.
   - A17 antes que A18: primero se unen los pedazos y después se buscan repetidos.
2. **Deduplicar películas** (A3, A4, A5, A6) y pasar las copias perdedoras a soft delete (G2).
3. **Reasignar reseñas** de copias perdedoras a la ganadora (G2).
4. **Resolver votos duplicados** (B13), que incluye los que aparecen recién en el paso 3.
5. **Soft delete de reseñas** sin usuario (B4), huérfanas (B11) o sin nada útil (B12), y **ocultar comentarios** basura (B7, B8).
6. **Recalcular `num_mflix_comments`** (A16), al final, cuando ya se sabe qué reseñas quedan visibles.

## 3. `movies`

### A3–A6 · Películas duplicadas

- **Problema:** la misma película aparece varias veces. Hay 651 grupos por `imdb.id` (1.348 documentos) y 4 pares más con `imdb.id` distinto.
- **Criterio (A3):** mismo `imdb.id`. Se descartó título + año porque da 21 falsos positivos (*Black Rain* de 1989 son dos películas: una de Ridley Scott y otra de Shōhei Imamura) y no detecta 37 grupos con el año o el título sucios.
- **Regla secundaria (A4):** distinto `imdb.id`, pero mismo título normalizado, año y duración, **y** al menos un campo identificatorio no vacío que coincida (`directors` o `cast`). Detecta exactamente *Confessions of a Dangerous Mind*, *Eros*, *Divide and Conquer* y *The Kingdom*, y ninguno de los 21 homónimos.
- **Fusión (A5, A6):** cada campo se toma de la copia más reciente (por `lastupdated`) que lo tenga válido. Si dos copias empatan en fecha, gana la que tiene más campos completos y, si siguen empatadas, el `_id` mayor. No se pierde información: por ejemplo, 9 años en `null` se recuperan de otra copia. La fusión entra a los subdocumentos y toma las listas enteras (ver sección 7, cambios del 2026-11-20).
- **Copias perdedoras (G2):** pasan a soft delete. Sus reseñas se reasignan a la ganadora (ver sección 5).

### P1 · `year`

- **Problema:** 123 con `è` (`'1981è'`), 113 `null`, 104 `'circa 1934'`, 90 texto numérico (`'1989'`), 4 rangos (`'2006è2007'`) y 90 negativos (`-1984`).
- **Regla:** extraer el número de 4 dígitos (`'1981è'` → 1981, `'circa 1934'` → 1934), pasar los negativos a positivos y, en los rangos de series, tomar el año de inicio (A9). Si queda `null`, se completa desde una copia duplicada (A5); si no hay copia, queda `null`.
- **Evidencia:** en las películas con una copia duplicada sana, el número rescatado coincide con el de la copia en todos los casos comparables (2.2).

### P2 · `runtime`

- **Problema:** 91 `'100 min'`, 88 `'122'`, 76 `'1h 25m'`, 91 `null`, 225 sin el campo y 78 negativos.
- **Regla:** convertir a minutos enteros (`'1h 25m'` → 85) y pasar los negativos a positivos (A11). Los valores altos **no** se recortan: hay series de 1.256 minutos y películas reales de 450 (*Satantango*). Los `null` y los faltantes se completan desde una copia duplicada si existe.
- **Evidencia:** las conversiones coinciden con la copia sana en todos los casos comparables (2.3).
- **Por qué minutos y no horas o texto:** es exacto (85 min son 1,4166… h), se ordena y filtra (`runtime < 120`) y es como ya viene el 98 % del dataset. El formato legible ("1 h 25 min") lo arma el frontend al mostrarlo.

### P3 · `genres`

- **Problema:** 378 películas tienen los géneros en un texto (`'Drama / Romance'`, `'Drama|History'`, `'Horror, Romance'`), y 614 elementos de lista tienen espacios sobrantes (`' Drama '`). Hay 43 sin el campo.
- **Regla:** partir el texto por `' / '`, `'|'` o `', '`, y recortar los espacios de cada elemento. Quedan 25 géneros distintos. Las películas sin el campo se dejan sin él.

### A12, A15, P5 · `imdb.rating`

- **Centinelas → `null` (A12, decidida):** `14.5` aparece 61 veces y no encaja en ninguna escala, `-1` aparece 57 veces y `''` 18 veces: 136 en total. El `14.5` **no** es un ×10: en las 4 películas que tienen otra copia con rating normal, esa copia dice 7.4, 6.1, 5.2 y 6.4 (no 1.45), y al fusionar se recupera ese valor (A5). Por eso esta regla se aplica **antes** que el ÷10. Se descartó `0` porque arrastra promedios, y no se imputa con un LLM porque no hay texto del que inferirlo.
- **Sin votos → `null` (A15, decidida):** un promedio sin cantidad de votos no tiene respaldo. Hoy afecta a 1 película, *This Is Spinal Tap*.
- **Escala ×10 → ÷10 (P5, decidida):** 132 valores entre 40 y 84 correlacionan 0,7 con `metacritic`, igual que los ratings normales, y solo 1 coincide con su propio `metacritic`. En 8 de las 9 películas con otra copia de rating normal, el valor ÷10 da exactamente ese rating (`64` → `6.4`). La excepción, *Turtles Can Fly* (`81` contra `8`), es la misma película medida en dos fechas: entre una copia y la otra entraron 79 votos.
- **Texto → número (P5, decidida):** 135 valores como `'7.2'`. En las 6 películas con otra copia comparable coincide exactamente.

### A14 · `imdb.votes`

Los 405 textos (`'1,208'`, `'1,109,724'`) se convierten a entero quitando las comas. Los 19 `''` pasan a `null`, no a `0`: un `0` diría "nadie votó", y en realidad no hay datos de IMDb. Las 405 conversiones se verificaron sin errores (4.2).

### P4 · `title`

417 títulos con espacios al inicio (201) o al final (216). **Regla:** recortarlos. No hay espacios dobles ni caracteres invisibles (2.6).

### A13 · Caracteres perdidos (`è`) — no se corrige

- **Problema:** todo carácter no ASCII de la fuente quedó como `è`: `Franèois` (ç), `Bjèrk` (ö), `Agustèn` (í). Son 13.250 apariciones en 4.933 películas (25 %), en todos los campos de texto. No es una anomalía inyectada: viene de la exportación original.
- **Por qué no se corrige:** la pérdida es de muchos a uno, así que el carácter original no está en el dataset y cualquier corrección es una predicción. El 74 % de los textos afectados son nombres de personas, donde un LLM adivina sin que se note. Un corrector con LLM además sería la opción más lenta (~13.500 llamadas) y la única paga.
- **Mejora futura:** buscar los nombres en una fuente externa por `imdb.id` (TMDB o Wikidata).

### A16 · `num_mflix_comments`

- **Problema:** coincide con la cantidad real de reseñas en solo 2.449 de 13.255 películas, y 4.154 películas tienen reseñas pero no tienen el campo. Los valores altos son de películas famosas (*Fight Club*: 417 contra 19 reales): parece venir de otros comentarios, no de `reviews`.
- **Regla:** recalcularlo al final de la limpieza como la cantidad de reseñas **visibles** (sin soft delete y sin comentario oculto). Desde ahí, todo servicio que cambie la visibilidad de una reseña lo actualiza.

### A17, A18 · Listas de personas

- **Nombres cortados (A17):** en 46 películas, un `split(",")` cortó comas que estaban dentro de un paréntesis: `'Claude Miller (scenario'` + `' adaptation and dialogue)'`. Si un elemento abre `(` sin cerrarlo, se le pegan los siguientes hasta que cierre. No se perdió ningún carácter, así que se reconstruye sin adivinar. Verificado: 0 películas siguen rotas.
- **Repetidos (A18):** 125 listas de `writers`, 2 de `cast` y 3 de `directors` tienen elementos repetidos. Se quitan solo los **idénticos** (con el rol incluido) y se conserva el orden. `'Amy Albany (memoir)'` y `'Amy Albany'` se quedan los dos, porque el rol es información.

### A19 · `released` vs. `year` — no se corrige

En 1.060 películas, el año de `released` difiere del de `year` en más de 1 año (*Godzilla*: 1954 contra 2004). No son errores: `released` es **una** fecha de estreno, que puede ser en otro país o un reestreno. `year` es el año de la película y es el que se muestra.

### A20 · `rated`

Se pasa a mayúsculas (`'Approved'` → `'APPROVED'`) y se unifica `UNRATED` con `NOT RATED`. Los códigos de otros países y épocas (`X`, `M`, `GP`, `PASSED`) **se dejan**: el dataset no dice de qué sistema es cada uno, así que convertirlos sería inventar. `NOT RATED` ("no tiene calificación") es distinto de que falte el campo ("no se sabe").

### A21, A22 · `lastupdated`

Se guarda como `Date`. Viene como texto en 2 formatos, y comparar texto puede ordenar mal. La limpieza **no** lo actualiza: indica cuándo cambió el dato en la fuente, y los cambios de la limpieza van a la auditoría.

### A23, A24 · `poster`

- **Servidor viejo (A23):** 1 película (*Sikumi*) usa `http://ia.media-imdb.com`, que responde `403`. Se reemplaza el servidor por `https://m.media-amazon.com` con la misma ruta, que sí devuelve la imagen. Esa imagen es la tapa del DVD *Cinema16*, que incluye el corto, y se deja porque es la que asignó la fuente.
- **Imágenes borradas (A24):** en una muestra de 300 películas (semilla 2026), 35 URLs dan `404`, aproximadamente un 12 % (entre 8 % y 15 %). Amazon borró las imágenes, así que ninguna regla las recupera. La limpieza **no** las toca: una URL que hoy funciona puede romperse mañana, así que el frontend tiene que mostrar un póster genérico cuando la imagen no carga.
- **Imágenes compartidas:** 12 URLs se repiten entre películas distintas: sagas (*Red Riding*), DVD que traen dos películas (*Aftermath / Genesis*) o duplicados de A4. No es un error.

### A25 · `awards`

- **Problema:** en 2.577 películas, `wins` y `nominations` no coinciden con `awards.text`. El premio grande del texto se sumó al primer número que aparecía después de *Another*, fuera una victoria o una nominación. *Blade Runner* (`'Nominated for 2 Oscars. Another 11 wins & 15 nominations.'`) tiene `wins: 13`, cuando le corresponde `wins: 11, nominations: 17`.
- **Regla:** recalcular los dos números a partir del texto (`Won N` → `wins`, `Nominated for N` → `nominations`). Si una frase no se puede leer, los números quedan como están y se registra en la auditoría.
- **Verificación:** el mecanismo del error reproduce el valor guardado en las 19.842 películas, ninguna frase quedó sin leer y cambian exactamente las 2.577 mal calculadas.

### A26, A27 · `tomatoes` — no se corrige

- **`critic` incompleto (A26):** 258 películas tienen `fresh`/`rotten` sin bloque `critic`, y 38 tienen solo `numReviews`. El dato falta, no está mal, y completarlo sería inventar lo que la fuente no publicó. Hay 1 excepción a `meter = fresh / (fresh + rotten)`: *Around the Block*, que también se deja.
- **`dvd` no confiable (A27):** 330 fechas son anteriores a 1996, el año en que salió el DVD (*Odd Girl Out*, de 2005: `1910-01-10`), y 89 son anteriores a la propia película.
- Si el proyecto termina usando `tomatoes`, se revisa (ver sección 8).

## 4. `reviews`

### B4 · Reseñas anónimas

459 reseñas tienen `user_id` vacío o `usr_0000`. Todas son `'Anonymous'` y tienen el email vacío, así que no hay forma de recuperar al usuario. Van a soft delete.

### B11 · Reseñas huérfanas

350 reseñas apuntan a 50 `movie_id` que no existen. Los ids tienen el prefijo de fecha de los `_id` de `reviews`, no de `movies`: son ids fabricados, no películas borradas. No hay a qué reasignarlas, así que van a soft delete.

### B5, B6, B14 · `rating`

- **Texto → número (B14):** 873 ratings como `'4'`.
- **Fuera de 1–5 → `null` (B5):** 1.211 reseñas con 10, 100, 999, -1, 0 o 6. No son otra escala: las reseñas con `10` dicen "4 stars" en el texto. Es ruido.
- **Recuperación:** de las 2.139 reseñas que quedan sin rating válido, 245 se recuperan con una regex que busca "N stars" en el texto (B6; coincide con el rating real en el 99,6 % de los casos válidos). Las 1.894 restantes tienen un comentario útil y el rating se infiere con el **LLM**.

### B7, B8 · Comentarios basura

- **Problema:** 1.315 comentarios basura (`''`, `'...'`, `'asdf'`, `'1234'`) y 268 sin contenido (`'nice'`, `'good'`, `'ok'`). El criterio es menos de 3 palabras: en la distribución hay un hueco entre 3 y 8 palabras.
- **Regla:** se **oculta el comentario** y se mantiene el voto, que sigue siendo válido para el promedio y el recomendador.

### B12 · Reseñas sin nada útil

Una reseña sin rating válido y con comentario basura va a soft delete. Hoy hay **0 casos**: todas las reseñas con rating inválido tienen un comentario útil. La regla se mantiene como protección.

### B2, B9, B10 · `date`

| Formato | Casos | Regla |
| :-- | --: | :-- |
| `Date` | 60.578 | Se deja; si es posterior a la creación del dataset (10/11/2026) → `null` (B10, 30 casos) |
| Entero | 177 | Epoch en milisegundos (en segundos darían el año 55.539) |
| `'dd/mm/yyyy'` | 179 | Día/mes: las 105 fechas no ambiguas son todas dd/mm (B2) |
| `'yyyy-mm-dd'` | 173 | ISO |
| `'circa 2023'` | 184 | `2023-01-01` con `datePrecision: "year"` (B9) |
| `'yesterday'` | 197 | `null` (B9) |

En todos los casos la reseña **se queda**: el problema está solo en la fecha. El valor original va a la auditoría.

### B1, B13 · Votos duplicados

- **Problema:** 448 pares en los que el mismo usuario votó dos veces la misma película (226 copias y 222 "Update: Changed my mind…"). Después de reasignar las reseñas de películas duplicadas, son **472** pares: 25 usuarios votaron dos copias de la misma película.
- **Regla (B13), en orden:**
  1. Solo cuentan las fechas **válidas**: posteriores al estreno y no posteriores a la creación del dataset (`circa N` cuenta como 1/1/N).
  2. Gana la fecha válida más reciente.
  3. Si empatan, gana el que empieza con "Update: Changed my mind".
  4. Si siguen empatados (copias idénticas), gana el `_id` mayor.

  El resto va a soft delete: 473 votos.
- **Consecuencias aceptadas:**
  - En 16 pares el "Update" tiene una fecha futura y **pierde**: la fecha manda sobre el texto.
  - En 3 pares el ganador es "peor" que el perdedor, porque el ruido le tocó por casualidad a la copia más reciente. En 1 tiene un rating inválido que se infiere con el LLM; en 2 tiene un comentario basura que se oculta.
- **Por qué no se mezclan votos:** un voto es lo que una persona dijo en un momento. Tomar el rating de uno y el comentario de otro inventaría una reseña que no existió. Promediar inventaría un rating que el usuario nunca dio.

## 5. Interacciones entre reglas

- **Reseñas de películas duplicadas (5.1):** 4.723 reseñas apuntan a películas duplicadas. De esas, 2.474 apuntan a una copia perdedora y se reasignan a la ganadora usando un mapa copia → ganadora, que se arma **antes** del soft delete.
- **Votos que se vuelven duplicados (5.2):** ver B13.
- **Reseñas con varias anomalías (5.4):** ninguna tiene más de 2, y todas las combinaciones salvo una incluyen un voto duplicado. Las anomalías se inyectaron por separado y solo se cruzan cuando un voto duplicado copia una reseña que ya tenía otro problema. La excepción (anónima + fecha futura) no genera conflicto, porque va a soft delete por B4.

## 6. Campos revisados sin problemas

Sin anomalías (4.13), así que el `cleaning-agent` no necesita reglas para ellos:

- `title`, `plot`, `fullplot`: ninguno vacío.
- `cast`, `countries`, `directors`, `genres`, `languages`, `writers`: ninguna lista vacía ni con elementos vacíos.
- `type`: solo `movie` (19.609) y `series` (233). Las series se incluyen (A10).
- `metacritic` entre 1 y 100; `tomatoes.critic.meter` y `viewer.meter` entre 0 y 100; `critic.rating` entre 0 y 10; `viewer.rating` entre 0 y 5.
- `fresh + rotten` coincide con `critic.numReviews` en todas las películas que tienen ese bloque.

## 7. Esquema limpio (contrato)

Lo que cualquier servicio puede asumir sobre la base después de la limpieza.

### General

- **Soft delete (G1, G2):** los documentos descartados no se borran. Se marcan con `deleted: true` y un motivo en `deletedReason`. **Todo servicio que lee tiene que filtrarlos** (`{ deleted: false }`). Los campos de esta sección están siempre presentes: si no aplican valen `false` o `null`.
- **`null` significa "no se sabe".** El valor original de todo campo corregido o anulado vive en la auditoría, no en el documento.

### `movies`

| Campo | Tipo | Garantía |
| :-- | :-- | :-- |
| `deleted` | `bool` | `true` en las copias duplicadas descartadas. |
| `deletedReason` | `string` o `null` | `"duplicateMovie"`; `null` si está activa. |
| `mergedInto` | `ObjectId` o `null` | `_id` de la copia ganadora, siempre una película activa; `null` si está activa. |
| `year` | `int` o `null` | Para series, año de inicio. `null` si no se pudo rescatar ni completar desde una copia. |
| `runtime` | `int` o `null` | Minutos, positivo. El frontend lo formatea para mostrarlo. Nunca falta: si no se sabe, `null`. |
| `genres` | lista de `string` | Sin espacios sobrantes. Puede faltar. |
| `title` | `string` | Sin espacios al inicio ni al final. |
| `imdb.rating` | `double` o `null` | Escala 0–10, nunca `0` como "desconocido". `null` si `imdb.votes` es `null`. |
| `imdb.votes` | `int` o `null` | Nunca texto ni `0` como "desconocido". |
| `num_mflix_comments` | `int` | Reseñas visibles. Crear una reseña suma 1; soft delete u ocultar el comentario resta 1. |
| `released` | `Date` | **Una** fecha de estreno, no necesariamente la primera. El año que se muestra es `year`. |
| `rated` | `string` en mayúsculas, o ausente | Puede ser de distintos países y épocas. `NOT RATED` = sin calificación; ausente = no se sabe. |
| `lastupdated` | `Date` | Fecha original de la fuente; la limpieza no la modifica. |
| `poster` | `string` | URL `https://m.media-amazon.com/…`. **Puede no cargar** (≈12 %): el frontend necesita un póster genérico. Puede ser una tapa de recopilación o compartirse entre películas. |
| `awards.wins`, `awards.nominations` | `int` | Coinciden con `awards.text`. |
| `tomatoes` | tal como viene | `critic` puede faltar o estar incompleto; `tomatoes.dvd` no es confiable. |
| texto (todos los campos) | `string` | Puede contener `è` como carácter perdido. Una búsqueda puede normalizar la consulta (todo carácter no ASCII → `è`) sin tocar los datos. |

### `reviews`

| Campo | Tipo | Garantía |
| :-- | :-- | :-- |
| `rating` | `int` 1–5, o `null` sin LLM | Puede venir del texto (regex o LLM); el origen queda en la auditoría. `null` solo en reseñas activas cuyo rating no se pudo recuperar con la regex mientras el LLM no esté habilitado (1.884). |
| `date` | `Date` o `null` | `null` si la fecha original era imposible o desconocida. |
| `datePrecision` | `"day"`, `"year"` o `null` | `"year"` para las `circa`: el frontend muestra solo el año. `null` si y solo si `date` es `null`. |
| `deleted` | `bool` | `true` si la reseña se descartó. |
| `deletedReason` | `string` o `null` | `"anonymous"` (B4), `"orphan"` (B11), `"duplicateVote"` (B13) o `"noContent"` (B12); `null` si está activa. Un solo motivo: el de la primera regla que la descarta. |
| `commentHidden` | `bool` | `true` si el comentario es basura o sin contenido (B7, B8). Distinto del soft delete: el voto sigue contando y el texto queda en la base, pero no se muestra. |
| `user_name`, `user_email` | `string` o ausente | Están en las reseñas del dataset. Las que crea el `ingest-consumer` no los tienen: se resuelven por `user_id` en `users` (README, "Pendiente"). |
| unicidad | — | Como máximo un voto visible por usuario y película. El `ingest-consumer` la garantiza con un índice único parcial (`one_active_vote`). |

### Aclaraciones acordadas (2026-11-19)

Confirmadas por el grupo al revisar el contrato desde el recomendador ([docs/recomendador.md](../docs/recomendador.md)):

- **`deleted` siempre presente:** todo documento activo tiene `deleted: false`, y los descartados, `deleted: true`. El campo nunca falta.
- ~~**LLM obligatorio:** hay API key, así que toda reseña activa tiene `rating` entero de 1 a 5, incluidas las ≈1.900 que se infieren del comentario (B5, B6). La marca `done` y `data.cleaned` se emiten con la inferencia terminada.~~ Reemplazada el 2026-11-23: ver "Sin LLM, `rating` admite `null`" más abajo.
- **Integridad referencial:** toda reseña activa apunta a una película activa (resultado de G2 y B11).
- **Listas de personas:** `directors`, `cast` y `writers` pueden faltar, igual que `genres`. En el crudo faltan en 238, 204 y 995 películas.
- **`plot` no se modifica:** ninguna regla lo cambia. La única excepción es la fusión de duplicados (A5), que puede quedarse con el plot de otra copia (2 de los 651 grupos). El recomendador embebe los plots mientras corre la limpieza, así que si una regla futura modifica `plot`, hay que avisarle.

### Cambios al implementar el `cleaning-agent` (2026-11-20)

Decisiones que el análisis no definía y aparecieron al escribir el código. Las tablas de arriba ya las incluyen.

- **`runtime` nunca falta:** las 225 películas sin el campo pasan a `runtime: null`, como pide el tipo "`int` o `null`". Después de la fusión quedan 310 activas en `null`.
- **`datePrecision` puede ser `null`:** lo es si y solo si `date` es `null` (227 reseñas con `yesterday` o fecha futura). Una precisión de día para una fecha desconocida diría algo falso.
- **Campos de soft delete:** además de `deleted`, las películas tienen `deletedReason` y `mergedInto`, y las reseñas, `deletedReason` y `commentHidden`. Están siempre presentes, igual que `deleted`.
- **Un solo motivo por reseña descartada:** se aplican en orden B4, B11, B13, B12 y queda el primero. En el dataset no hay solapamientos que cambien los números: ningún voto duplicado es huérfano, y las anónimas no participan de B13.
- **Alcance de la fusión (A5):** entra a los subdocumentos, así que `imdb.rating` puede venir de otra copia aunque el resto de `imdb` sea de la ganadora. Las listas (`cast`, `genres`, …) se toman enteras de una sola copia, porque mezclarlas inventaría un elenco que no existe. `num_mflix_comments` no se fusiona porque se recalcula al final (A16).
- **`tomatoes` mezclado en 2 películas:** en *Confessions of a Dangerous Mind* y *Divide and Conquer*, unidas por A4 (cada copia tenía su propio `imdb.id` y su propio registro de Rotten Tomatoes), la fusión completó `critic`, `fresh`, `rotten`, `viewer` y otros subcampos desde la otra copia. Los datos quedan coherentes entre sí (`fresh + rotten = critic.numReviews`), pero `tomatoes.lastUpdated` es el de la ganadora. **Se deja así** porque `tomatoes` no se usa (A26). Si se empieza a usar, conviene tratarlo como un bloque que no se mezcla.
- **Reseñas para el LLM: 1.884, no 1.894.** El rating se infiere solo en reseñas activas, y 10 de las 1.894 van a soft delete (anónimas, huérfanas o votos duplicados).
- **Qué no va a la auditoría:** los campos que se agregan sin corregir un valor (`deleted: false`, `deletedReason: null`, `datePrecision`, el `runtime: null` de un campo faltante) y los cambios de tipo sin cambio de valor (`imdb.rating` `7` → `7.0`). Todo lo demás registra campo, regla, valor original y valor nuevo.
  - **`lastupdated` (A21) tampoco va a la auditoría:** viene como texto en las 19.842 películas, así que convertirlo a `Date` es preparar el formato, no corregir una anomalía. Registrarlo era el 42 % de los cambios de `movies` y hacía que la métrica "películas modificadas" diera 100 %. El original queda en `moviesRaw`.
  - **En cambio, `'1989'` → `1989` (P1) y `'4'` → `4` (B14) sí van**, aunque el valor sea el mismo: el texto aparece solo en algunos documentos, es suciedad del dataset y detectarla es parte del trabajo del agente. **Criterio:** se registra lo que corrige una anomalía (algo que distingue a unos documentos de otros); no se registra una conversión de formato que se aplica igual a todos ni un cambio de representación sin significado. La auditoría es lo que muestra `/audit`, no un respaldo del original.
- **Forma de la auditoría: un registro por documento.** Lleva el mismo `_id` que la película o la reseña y la lista de sus cambios en el orden en que se aplicaron. Repetir la limpieza reemplaza el registro en lugar de duplicarlo, y el detalle de un documento es una sola lectura. Las métricas por regla se calculan desarmando las listas (`$unwind`). La lista tiene techo: el máximo son 10 cambios (*Confessions of a Dangerous Mind*). Sobre el dataset: 18.105 películas con 26.894 cambios y 8.155 reseñas con 8.608 cambios, sin contar el LLM.
- **Caída a mitad de la limpieza: se repite desde el crudo, no se retoma.** Antes de escribir nada, el agente copia `movies` y `reviews` a `moviesRaw` y `reviewsRaw` (una sola vez; la marca registra que la copia está completa y nunca se vuelve a copiar desde `movies`, que podría estar a medio limpiar). Cada corrida lee de esa copia, reemplaza cada documento por `_id` y escribe la auditoría sin duplicados, así que correrla dos veces da lo mismo que una. Si al arrancar la marca dice `running`, se repite todo. **Todo servicio que lee usa `movies` y `reviews`; las copias `Raw` son solo del agente.**
  - **Por qué no se retoma desde donde quedó (puntos de control):** la limpieza es global, no se divide en lotes independientes. La fusión de duplicados cambia películas y reseñas a la vez, y el contador de reseñas depende de todas las reseñas, así que no hay un "lote 3 de 10" que se pueda dar por terminado. Además, rehacer las reglas cuesta segundos: retomar agrega complejidad sin ahorrar tiempo.
  - **Otras opciones descartadas:** escribir en colecciones aparte y renombrarlas al final (el renombre es atómico por colección, pero no entre `movies`, `reviews` y la auditoría: una caída entre dos renombres pierde el crudo de una sola) y transacciones (el Mongo del compose no es replica set, y una transacción de 80.000 documentos choca con sus límites).
  - **Pendiente para el LLM:** repetir no puede significar volver a pagar ≈1.900 llamadas; sus respuestas se guardan para reusarlas (se define al implementarlo).
- **Colecciones nuevas del agente.** Además de `moviesRaw` y `reviewsRaw` (solo del agente):

  | Colección | Documento | Quién la lee |
  | :-- | :-- | :-- |
  | `cleaning` | Uno solo, `_id: "state"`: `status` (`pending`, `running` o `done`; sin documento equivale a `pending`), `rawCopied`, `eventPublished`, `startedAt`, `finishedAt` | El `backend` (`status`, para `GET /status`) y el `recommender` (¿`done`?) |
  | `audit` | Uno por documento con cambios: `_id` (el de la película o la reseña), `collection` (`"movies"` o `"reviews"`) y `changes`, una lista de `{field, rule, before, after, note}` en orden | El `backend`, para `/audit` |

- **`data.cleaned` sale al menos una vez, no exactamente una.** La marca anota si el evento salió (`eventPublished`). Si el agente se cae entre guardar `done` y publicar, al arrancar ve `done` sin publicar y publica. Si la limpieza se repite tras una caída, también vuelve a publicar. **El `recommender` tiene que tolerar un evento repetido**: hoy lo cumple, porque cada `data.cleaned` recalcula todo desde la base. El mensaje es JSON con la hora de fin: `{"finishedAt": "2026-11-20T20:23:33.962000"}`.
- **Si la limpieza falla** (por ejemplo, se cae Mongo mientras escribe), el proceso termina con código 1, Docker lo reinicia y la limpieza se repite desde el crudo. Comprobado deteniendo Mongo en plena limpieza.

### Sin LLM, `rating` admite `null` (2026-11-23)

- **Decisión:** el LLM queda en pausa hasta definir el proveedor y la key. Sin `LLM_API_KEY`, las 1.884 reseñas activas cuyo rating no recupera la regex (B6) quedan con `rating: null`, y la marca `done` y `data.cleaned` se emiten igual. Reemplaza la aclaración "LLM obligatorio" del 2026-11-19.
- **Por qué:** la app tiene que funcionar sin API key (README, D15), así que el contrato no puede prometer algo que depende de ella. `null` ya significa "no se sabe" en todo el contrato.
- **Qué hacen los que leen:** no cuentan esas reseñas como votos. Cómo se muestran (por ejemplo, el comentario sin estrellas) lo define el `frontend`. El `recommender` ya las descarta (recomendador, pendiente 10).
- **Cuando se habilite el LLM:** vuelve a valer "toda reseña activa tiene `rating` de 1 a 5".

## 8. Pendientes

### Para el grupo

1. **¿Qué campos de `movies` usan la ficha y el recomendador?** Define cuánto invertir en cada campo. Por ejemplo, `tomatoes` (A26, A27) hoy no se corrige porque no se sabe si se usa.
2. ~~**`mergedInto` en las copias fusionadas.**~~ Resuelto (2026-11-20): se incluye en el contrato (sección 7).
3. **Promedio de estrellas vs. contador de reseñas (A16):** el promedio incluye los votos de reseñas con comentario oculto y el contador no, así que pueden no coincidir ("★ 4.2 (8 reseñas)" calculado con 10 votos). Hay que decidir si se muestran votos y reseñas por separado o si se documenta.
4. **Sugerencia, no es parte del contrato: medir cuánto tarda la limpieza completa.** El profesor tiene que poder probar la app en unos 10 minutos desde cero. El recomendador tarda ≈6 minutos en embeber los plots y lo hace en paralelo con la limpieza (recomendador, 4.4), así que sirve saber cuál de los dos termina último. **Medición parcial (2026-11-20):** las reglas sin LLM tardan ≈4 s sobre todo el dataset, en memoria, y **≈12 s contra Mongo desde cero** (copia cruda, lectura, limpieza y escritura de documentos y auditoría). Falta medir la inferencia con el LLM (≈1.900 llamadas), que va a ser la parte lenta.
5. **Revisar los nombres nuevos que leen el `backend` y el `recommender`:** la marca en `cleaning` (`_id: "state"`, campo `status`), la auditoría en `audit` y el mensaje de `data.cleaned` (sección 7, cambios del 2026-11-20).

### Para la cátedra

1. **Pósters rotos (A24):** ¿vale la pena recuperarlos desde TMDB buscando por `imdb.id`, o alcanza con el póster genérico en el frontend?

## 9. Limitaciones conocidas

- **Caracteres `è` (A13):** el 25 % de las películas tiene texto con caracteres perdidos, y no se corrige en esta versión.
- **Homónimos en listas de personas (A18):** dos personas con el mismo nombre exacto se tratan como repetidas. Tampoco se distinguirían en pantalla.
- **`circa` frente a una fecha exacta del mismo año (B13):** no se puede saber cuál es posterior. Hoy no hay casos.
- **Pósters (A24):** el ≈12 % de imágenes rotas es una estimación por muestra, y la cifra cambia con el tiempo.
- **`released`, `tomatoes.dvd` y `tomatoes.critic`** se conservan como vienen aunque tengan valores dudosos.
- **`tomatoes` de dos copias (A5):** en 2 películas fusionadas por A4, `tomatoes` combina subcampos de dos registros distintos (ver sección 7, cambios del 2026-11-20).
