# Motor de recomendaciones

> **Estado: estrategia en discusión, sin implementar (2026-11-19).** Este documento registra las decisiones tomadas sobre el algoritmo del `recommender`, las que faltan y por qué se descartaron las alternativas. Los números se midieron sobre el dataset **sin limpiar**. Hay que recalcularlos sobre la base limpia, aunque no deberían cambiar mucho.

El `recommender` sirve dos cosas al `backend`:

- **"Recomendadas para vos":** películas para un usuario, según sus votos.
- **"Películas similares":** películas parecidas a una dada.

Entrena o indexa al recibir `data.cleaned` y responde desde estructuras en memoria (ver el [README](../README.md#recomendaciones)).

- **Estados:** **decidida**, **propuesta** (falta confirmar), **abierta** (falta definir) o **descartada**.
- **Datos limpios:** se asume el [esquema limpio de ANOMALIAS](../analysis/ANOMALIAS.md#7-esquema-limpio-contrato). Las referencias "ANOMALIAS, A12" apuntan a sus reglas.

## 1. Resumen

| # | Tema | Decisión | Estado |
| :-- | :-- | :-- | :-- |
| R1 | Usuarios | No se crean desde la app: se elige uno de una lista, que incluye usuarios nuevos precargados sin votos | decidida |
| R2 | Usuario sin votos | Ranking por promedio bayesiano | decidida |
| R3 | Fuentes del ranking | Votos propios e `imdb.rating` | decidida |
| R4 | Combinación votos propios + IMDb | Ver [3.3](#33-combinación-con-imdb) | abierta |
| R5 | Valor de `m` | Entre 5 y 15 para los votos propios | abierta |
| R6 | Filas por género en la portada | Mismo ranking bayesiano, filtrado por género | propuesta |
| R7 | Onboarding (preguntar gustos al entrar) | No hacerlo: en la demo, los votos cumplen ese papel | propuesta |
| R8 | Usuario con votos | Por contenido, con tres señales: plot, géneros y personas | decidida |
| R9 | Pesos de las tres señales | Se ajustan con la evaluación | abierta |
| R16 | Señal faltante en una película | Pesos fijos: el término vale 0 y no se redistribuye | decidida |
| R10 | Perfil del usuario | Suma de vectores ponderada por `estrellas − punto medio` | propuesta |
| R11 | Filtrado colaborativo | No se usa: no hay votos suficientes | descartada |
| R12 | Híbrido contenido + colaborativo | No aplica, por R11 | descartada |
| R13 | Evaluación | División temporal por usuario, contra el ranking de popularidad | propuesta |
| R14 | Modelo de embeddings del plot | Local, dentro del contenedor: se descarga en el build y embebe al arrancar | decidida |
| R15 | Cálculo por petición | Vecinos precalculados, o producto contra todo el catálogo | abierta |
| R17 | Cuándo se embebe | Al arrancar, en paralelo con la limpieza, con el hash del plot como clave | propuesta |

## 2. Datos disponibles

| Dato | Valor | Implicancia |
| :-- | :-- | :-- |
| Películas | 19.842 (unas 700 son copias duplicadas que la limpieza fusiona) | Metadata rica: `plot`, `genres`, `directors`, `cast`, `writers`, `imdb` |
| Votos válidos (1–5) | 58.476, de 2.002 usuarios | |
| Votos por usuario | mínimo 10, mediana 25 | Los usuarios del dataset no están en frío; los precargados nuevos, sí (R1) |
| Películas con al menos un voto | 12.413 | Unas **7.400 no tienen ningún voto** |
| Votos por película | mediana 2; el 40 % tiene uno solo | Muy pocos votos por película: ver R11 |
| Densidad usuario × película | 0,24 % | |
| Promedio global de votos (C) | 3,525 | |

Votos por película, sobre las 12.413 que tienen al menos uno:

| Votos | Películas | % | Acumulado |
| :-- | --: | --: | --: |
| 1 | 4.980 | 40,1 % | 40,1 % |
| 2 | 2.193 | 17,7 % | 57,8 % |
| 3–4 | 2.172 | 17,5 % | 75,3 % |
| 5–9 | 1.540 | 12,4 % | 87,7 % |
| 10–16 | 226 | 1,8 % | 89,5 % |
| 17–21 | 606 | 4,9 % | 94,4 % |
| 22 o más | 696 | 5,6 % | 100 % |

La columna **Acumulado** es el percentil. Por ejemplo, el 75 % de las películas tiene 4 votos o menos, así que el percentil 75 es 4.

## 3. Usuario sin votos

### 3.1 · Promedio bayesiano (R2)

Ordenar por el promedio simple de estrellas no sirve: una película con un único voto de 5 queda primera. Se usa el promedio bayesiano, la misma fórmula del ranking de IMDb:

```
WR = (v·R + m·C) / (v + m)
```

| Término | Significado |
| :-- | :-- |
| `R` | Promedio de estrellas de la película |
| `v` | Cantidad de votos de la película |
| `C` | Promedio de todos los votos de la base: el valor que se asume para una película de la que no se sabe nada |
| `m` | Cantidad de votos ficticios de valor `C` que se le agregan a cada película: cuánta evidencia se exige antes de creerle a su propio promedio |

El peso del promedio propio es `v / (v + m)`. Cuando `v = m`, la película pesa 50 % su promedio y 50 % el global. Ejemplo con `m = 5` y una película con todos votos de 5:

| `v` | `WR` | Peso de `R` |
| --: | --: | --: |
| 1 | 3,77 | 17 % |
| 5 | 4,26 | 50 % |
| 20 | 4,70 | 80 % |

También funciona hacia abajo: un único voto de 1 deja la película en 3,10, no la hunde.

Top 5 con `m = 5`. Por promedio simple, en cambio, arriba quedan películas con 3 o 4 votos:

| `v` | `R` | `WR` | Película |
| --: | --: | --: | :-- |
| 22 | 4,95 | 4,69 | Planet Earth |
| 16 | 4,88 | 4,55 | Band of Brothers |
| 18 | 4,83 | 4,55 | The Shawshank Redemption |
| 15 | 4,80 | 4,48 | The Godfather |
| 14 | 4,71 | 4,40 | The Godfather: Part II |

### 3.2 · Valor de `m` (R5)

IMDb elige `m` como un percentil de la cantidad de votos por película: así sale de los datos y crece si el catálogo crece. En nuestros datos hay un salto: casi no hay películas con 10 a 16 votos. Arriba de ese salto hay unas 1.300 películas con 17 o más; abajo, el resto, con pocos votos.

| `m` | Efecto |
| :-- | :-- |
| 17 (percentil 90) | Compiten prácticamente solo las ~1.300 muy votadas. Lista confiable, pero siempre la misma. |
| 5 | Entran también las de 5 a 9 votos (~3.000 en total). Más variedad, algo más de ruido. |

**Propuesta:** entre 5 y 15. El valor final se elige con la evaluación (R13).

### 3.3 · Combinación con IMDb

`imdb.rating` (escala 0–10) e `imdb.votes` están en casi todas las películas, incluidas las ~7.400 sin votos propios, que sin IMDb quedarían todas empatadas en `C`. La limpieza garantiza un `double` y un `int`, o `null` en ambos (ANOMALIAS, A12, A14, A15).

Falta decidir cómo se combinan las dos fuentes (R4). Las escalas son distintas: IMDb va de 0 a 10 con miles de votos por película; la nuestra, de 1 a 5 con pocos. Cada fuente necesitaría su propio `m`, y en IMDb estaría en los miles.

### 3.4 · Presentación (R6, R7)

- **Filas por género (propuesta):** en lugar de una sola lista, una fila por género ("Lo mejor en Comedia", "Lo mejor en Acción"), con el mismo ranking filtrado. Da variedad y facilita encontrar algo para votar. Después de la limpieza quedan 25 géneros.
- **Onboarding (propuesta: no hacerlo):** sería una pantalla inicial que pide géneros favoritos o unos votos. En la demo, los profesores eligen un usuario nuevo y votan, y eso ya cumple ese papel.

## 4. Usuario con votos: por contenido (R8)

### 4.1 · Similitud entre películas

```
similitud(A, B) = w₁·cos(plot_A, plot_B) + w₂·cos(géneros_A, géneros_B) + w₃·cos(personas_A, personas_B)
```

| Señal | Representación | Qué aporta |
| :-- | :-- | :-- |
| Plot | Embedding del texto de `plot` | De qué trata la película. Generaliza: dos tramas de atracos quedan cerca aunque no compartan personas. |
| Géneros | Una posición por género | Señal gruesa, con peso propio. |
| Personas | Una posición por persona de `directors`, `cast` y `writers` | Autor, estilo y época, que el texto no dice. Solo detecta coincidencias exactas. |

La misma similitud sirve para "Películas similares".

**Plot:**

- Se usa `plot` y no `fullplot`. `plot` está en todas las películas; `fullplot` falta en unas 300 y es largo, y los modelos chicos cortan el texto (alrededor de 256 sub-palabras).
- El modelo y su uso se detallan en [4.4](#44--embeddings-del-plot-r14-r17).

**Personas:**

- **No es un embedding de los nombres.** El nombre no significa nada para la cuenta; lo que aporta es que dos películas lo compartan. El 75 % de las películas comparte director con alguna otra, y el 90 % comparte al menos un actor.
- **Ponderación por rareza (TF-IDF):** compartir a alguien que aparece en 3 películas dice más que compartir a alguien que aparece en 60.
- **Se quitan los nombres que aparecen en una sola película:** nunca coinciden con nada. Medido por campo, de unos 76.000 nombres distintos quedan unos 22.000.
- **Se quita el rol entre paréntesis:** la limpieza lo conserva (ANOMALIAS, A18), y sin quitarlo `'Stephen King (novel)'` y `'Stephen King'` no coinciden.
- **El carácter perdido `è` (A13) no afecta:** un mismo nombre queda escrito igual en todas sus películas, así que las coincidencias se mantienen.

**Señal faltante (R16):** con pesos fijos, si una película no tiene una señal, ese término vale 0 y los otros dos quedan igual. No se redistribuye su peso. Medido sobre el dataset crudo:

| Caso | Películas |
| :-- | --: |
| Sin `directors`, `cast` ni `writers` | 0 |
| Con personas, pero ninguna compartida con otra película | 990 |
| Sin `genres` | 43 |
| Sin `genres` ni personas compartidas (solo les queda el plot) | 7 |

Con la limpieza, las 990 pueden subir un poco: hoy algunas comparten nombres solo con su propia copia duplicada.

Para personas, el 0 es el caso normal: el **99,8 %** de los pares de películas no comparte a nadie (cada película comparte alguna persona con una mediana de 26 otras). Una película sin personas está en la misma situación que casi cualquier otra frente a casi todo el catálogo: no recibe un bonus que casi nadie recibe.

Alternativas descartadas:

| Alternativa | Por qué no |
| :-- | :-- |
| Renormalizar: dividir por la suma de los pesos de las señales presentes | "No se sabe" le gana a "se sabe que no coinciden": las películas con menos metadata suben en todas las listas |
| Imputar el valor típico de la señal | Para personas da lo mismo que pesos fijos (el valor típico es ≈ 0) |
| Coseno sobre el vector concatenado | Renormaliza a medias, sin control explícito |

En "Películas similares a A", si a A le falta una señal, el término es igual contra todas las candidatas y el orden no cambia: la regla solo importa cuando la que no tiene la señal es la candidata. Pesos fijos también permite calcular el puntaje como un solo producto de matrices (R15). Si la evaluación (R13) mostrara que renormalizar da mejor NDCG, se revisa.

### 4.2 · Perfil del usuario (R10)

El perfil es la suma de los vectores de las películas que votó, cada uno **multiplicado** por `estrellas − punto medio`:

| Estrellas | Peso (punto medio 3) | Efecto |
| :-- | --: | :-- |
| 5 | +2 | Acerca el perfil a la película, con fuerza |
| 4 | +1 | Lo acerca |
| 3 | 0 | No aporta |
| 2 | −1 | Lo aleja |
| 1 | −2 | Lo aleja con fuerza |

Ejemplo con vectores de 2 dimensiones `[acción, romance]`: Mad Max `(1, 0)` con 5 ★, Die Hard `(0,9, 0,1)` con 4 ★ y Titanic `(0, 1)` con 1 ★ dan `2·(1, 0) + 1·(0,9, 0,1) − 2·(0, 1) = (2,9, −1,9)`. El perfil apunta a la acción y se aleja del romance.

**Punto medio:** un 3 fijo supone que todos usan la escala igual, y para quien pone 4 a casi todo, un 3 es una mala nota. Se propone usar el promedio del usuario, corregido hacia `C` como en 3.1: `(n·promedio_usuario + k·C) / (n + k)`. Sin esa corrección, un usuario nuevo con un solo voto tendría peso 0 y el perfil quedaría vacío. El valor de `k` queda abierto.

Se recomiendan las películas más cercanas al perfil (por coseno), excluyendo las que ya votó.

### 4.3 · Ajuste final de la lista (propuesta)

- **Piso de calidad:** sumar un término `β·WR` al puntaje, para que la cercanía al perfil no saque películas malas.
- **Diversidad (MMR):** penalizar candidatos muy parecidos a los ya elegidos, para no devolver diez películas casi iguales.

### 4.4 · Embeddings del plot (R14, R17)

**Qué es un embedding acá:** el modelo ya viene entrenado y no se ajusta con nuestros datos. Embeber es aplicar una función fija, `vector = f(plot)`, que depende solo del texto y de la versión del modelo. No depende de los votos, de los usuarios ni de las demás películas. Lo que sí se aprende de nuestros datos (TF-IDF de personas, `WR`, perfiles, vecinos) se calcula al recibir `data.cleaned`.

**Decisión (R14):** el modelo corre dentro del contenedor `recommender`. Se descarga en el `docker build`: los `RUN` del Dockerfile usan la red de build, que tiene internet. En ejecución, el contenedor sigue en `internal-net`, sin salida (criterio 4 del esqueleto).

Medido en una PC con Windows y 4 CPUs, con `fastembed` (ONNX, sin torch) y `sentence-transformers/all-MiniLM-L6-v2`:

| Paso | Tiempo | Tamaño |
| :-- | --: | --: |
| Instalar `fastembed` | 79 s | 182 MB |
| Descargar y cargar el modelo | 11 s | 273 MB |
| Embeber los 19.842 plots | **376 s** | 384 dimensiones |

**Restricción:** el profesor tiene que poder probar la app en unos 10 minutos desde cero, y el build con la carga del dataset ya tarda 264 s (esqueleto, F7). Los 6 minutos de embeddings no entran si se hacen después de la limpieza.

**Propuesta (R17): embeber en paralelo con la limpieza.**

- Al arrancar, el `recommender` lee los `plot` crudos y los embebe sin esperar `data.cleaned`. Puede hacerlo porque la limpieza no modifica `plot`: no hay ninguna regla sobre ese campo (ANOMALIAS, sección 6).
- **La clave es un hash del texto, no el `_id`.** Al fusionar duplicados, cada campo se toma de la copia más reciente que lo tenga válido (ANOMALIAS, A5), así que el `plot` de la ganadora puede venir de una copia perdedora. Pasa en 2 de los 651 grupos (*Little Fugitive*, *The Personals*). Como se embeben los plots de todas las copias, el plot ganador siempre está.
- Al recibir `data.cleaned`, se busca el vector de cada película activa por el hash de su `plot`. Si no está (un plot nuevo o modificado), se embebe en el momento.
- Los vectores se guardan en un volumen del `recommender`, para que el segundo arranque no embeba de nuevo (pendiente 7). En MongoDB no, porque el `recommender` solo lee de ahí.
- Falta medir cuánto tarda la limpieza: si tarda más que el embedding, este último queda oculto.

**Alternativas descartadas:**

| Alternativa | Por qué no |
| :-- | :-- |
| El `cleaning-agent` calcula los embeddings | Es trabajo del recomendador; el que limpia no genera información nueva |
| API de embeddings en la nube | El `recommender` necesitaría salida a internet y una key; sin key no habría recomendaciones |
| Vectores precalculados y commiteados en el repo (≈15 MB) | Daban los mismos vectores sin costo al arrancar. El grupo eligió el modelo local al arrancar |

## 5. Descartado: filtrado colaborativo (R11, R12)

El filtrado colaborativo recomienda según quién votó qué, sin mirar el contenido: "a quienes les gustó X también les gustó Y". Puede funcionar comparando películas (item-item) o factorizando la matriz usuario × película. En los dos casos necesita **muchas películas con votantes en común**, y este dataset no las tiene:

- La mediana es de **2 votos por película**, y el **40 %** de las películas votadas tiene uno solo.
- Unas **7.400 películas no tienen ningún voto**, así que el método no puede ubicarlas.
- La matriz usuario × película está ocupada en un **0,24 %**.

Con estos datos, el colaborativo no aporta información que no dé el contenido, y agrega un modelo más para entrenar y mantener. Por eso se descarta, y con él el híbrido contenido + colaborativo. El híbrido que queda es contenido + calidad (4.3).

## 6. Evaluación (R13, propuesta)

Las reseñas tienen fecha, así que para cada usuario se entrena con sus votos más viejos y se evalúa con los últimos N. Se compara el ranking de popularidad (3.1) contra el modelo por contenido, con precision@10 y NDCG@10. La comparación sirve para:

- ajustar los pesos `w₁`, `w₂`, `w₃` y `β`, y el valor de `m`;
- justificar el modelo con números: si el contenido no le gana a la popularidad, no aporta.

## 7. Integración con la arquitectura

- **Filtrar `deleted: true`** en `movies` y en `reviews` (ANOMALIAS, G1). Si no, se recomiendan copias duplicadas y cuentan votos anónimos, huérfanos o repetidos.
- **Aclaraciones del contrato:** acordadas con el grupo y registradas en [ANOMALIAS, sección 7](../analysis/ANOMALIAS.md#aclaraciones-acordadas-2026-11-19). Para el recomendador implican:
  - Filtrar con `deleted: false`, porque el campo siempre está.
  - Todo voto activo tiene `rating` de 1 a 5.
  - Todo voto activo apunta a una película activa.
  - `directors`, `cast` y `writers` que faltan se tratan como listas vacías.
  - El `plot` se puede embeber antes de que termine la limpieza (R17).
- **Votos nuevos:** llegan a MongoDB por `ingest-consumer`. Como el perfil (4.2) es una suma, se puede armar en cada petición, leyendo los votos del usuario con una consulta indexada por `user_id`, sin reentrenar.
- **Cálculo por petición (R15):** el README pide que ninguna petición calcule similitudes contra todo el catálogo. Hay dos opciones:
  - Precalcular los ~50 vecinos más cercanos de cada película y armar la recomendación juntando los vecinos de lo que el usuario votó bien. Respeta la regla.
  - Relajar la regla: el producto del perfil contra una matriz de 20.000 × 384 tarda pocos milisegundos y entra en el objetivo de < 100 ms.
  
  Una matriz de similitud completa (20.000 × 20.000) no entra: ocupa unos 1,6 GB.

## 8. Campos que usa el recomendador

Responde al pendiente 1 de ANOMALIAS ("¿Qué campos de `movies` usan la ficha y el recomendador?"):

| Colección | Usa | No usa |
| :-- | :-- | :-- |
| `movies` | `plot`, `genres`, `directors`, `cast`, `writers`, `imdb.rating`, `imdb.votes`, `deleted` | `fullplot`, `tomatoes`, `awards`, `metacritic`, `released`, `rated`, `runtime`, `year` |
| `reviews` | `user_id`, `movie_id`, `rating`, `deleted` | `comment`, `date` (solo para la evaluación) |

Para el recomendador, `tomatoes` puede quedar sin corregir. La ficha puede necesitar otros campos.

## 9. Pendientes

1. Cómo combinar los votos propios con IMDb (R4).
2. El valor de `m` (R5) y el de `k` para el punto medio (R10).
3. Confirmar las filas por género (R6) y no hacer onboarding (R7).
4. Confirmar que se embebe en paralelo con la limpieza (R17). Saber cuánto tarda la limpieza queda como sugerencia para el `cleaning-agent` (ANOMALIAS, pendiente 4).
5. Vecinos precalculados o producto por petición (R15).
6. Pesos de las señales (R9), definidos con la evaluación (R13).
7. Guardar los vectores en un volumen, para que el segundo arranque tarde pocos segundos (ya figura en el README; ver 4.4).
8. Recalcular los números de la sección 2 sobre la base limpia.
