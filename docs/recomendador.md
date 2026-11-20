# Motor de recomendaciones

> **Estado: implementado en [services/recommender](../services/recommender/) (2026-11-20).** Este documento registra las decisiones sobre el algoritmo del `recommender` y por qué se descartaron las alternativas. La sección 9 junta lo necesario para implementarlo, y 9.6 describe la implementación y lo medido en los contenedores. Los números de las secciones 2 a 7 se midieron sobre el dataset **sin limpiar** con los scripts de [analysis/recomendador](../analysis/recomendador/). Los que calcula el servicio sobre la base limpia coinciden (9.6); falta recalcular el resto (pendiente 7).

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
| R4 | Combinación votos propios + IMDb | IMDb, con su propio bayesiano, es el punto de partida, y los votos propios lo corrigen (ver [3.3](#33--combinación-con-imdb-r4)) | decidida |
| R5 | Valores de `m` y `M` | `m = 5` (medido), `M = 3.000` (por criterio); el pasaje a 1–5 se recalcula al indexar | decidida |
| R6 | Filas por género en la portada | Mismo ranking bayesiano, filtrado por género | decidida |
| R7 | Onboarding (preguntar gustos al entrar) | Elegir de 1 a 3 géneros; ordenan la portada y no entran en el puntaje por contenido. El `backend` los guarda y arma la portada (ver 3.5) | decidida |
| R8 | Usuario con votos | Por contenido, con tres señales: plot, géneros y personas | decidida |
| R9 | Pesos de las tres señales | Cada señal se calibra por su 10.º vecino típico; pesos plot 0,2 · géneros 0,4 · personas 0,4, elegidos con la prueba de conjuntos escondidos y con un mínimo para el plot (ver 6.3) | decidida |
| R16 | Señal faltante en una película | Pesos fijos: el término vale 0 y no se redistribuye | decidida |
| R10 | Perfil del usuario | Cada voto pesa `estrellas − punto medio`, con `k = 5` para el punto medio, y se aplica sobre los vecinos precalculados (ver 4.2) | decidida |
| R11 | Filtrado colaborativo | No se usa: no hay votos suficientes | descartada |
| R12 | Híbrido contenido + colaborativo | No aplica, por R11 | descartada |
| R13 | Evaluación | Calidad: con los votos del dataset. Gustos: prueba automática de conjuntos escondidos, sin intervención humana | decidida |
| R14 | Modelo de embeddings del plot | Local, dentro del contenedor: se descarga en el build y embebe al arrancar | decidida |
| R15 | Cálculo por petición | Vecinos precalculados: 100 por película al indexar; la petición solo lee y suma (ver 7.1) | decidida |
| R17 | Cuándo se embebe | Al arrancar, en paralelo con la limpieza, con el hash del plot como clave | decidida |
| R18 | Actualización del `WR` | Se recalcula en segundo plano cada 60 s, fuera de las peticiones | decidida |
| R19 | Ajuste final de la lista | Piso de calidad `β = 0,2` y diversidad MMR con `λ = 0,8` (ver 4.3 y 6.3) | decidida |

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

**Reemplazado por 3.4:** este análisis usaba `C` como punto de partida. Con IMDb como punto de partida (R4), se midió `m = 5`.

### 3.3 · Combinación con IMDb (R4)

Hay dos fuentes:

- **Votos propios:** las reseñas de la base, de 1 a 5. Son las del dataset más las que se cargan en la app.
- **IMDb:** `imdb.rating` (promedio de 0 a 10) e `imdb.votes` (cuánta gente votó). La limpieza garantiza un `double` y un `int`, o `null` (ANOMALIAS, A12, A14, A15).

Medido en el crudo:

| Dato | Valor |
| :-- | :-- |
| Películas con `imdb.rating` válido | 19.705 de 19.842 |
| Películas sin votos propios | 7.440; 7.392 de ellas tienen IMDb |
| `imdb.votes` por película | Mediana 2.900; percentil 10: 337; percentil 90: 59.945 |
| Promedio de `imdb.rating` | 6,67 |
| Correlación entre el promedio propio y `imdb.rating` | 0,66 con ≥ 1 voto propio; 0,79 con ≥ 5; **0,80** con ≥ 17 |

**Cuantos más votos propios tiene una película, más se parece su promedio a IMDb.** Los votos del dataset son, en la práctica, una versión ruidosa de IMDb con muy pocos votantes (ver también 6.1). IMDb tiene la misma información, con miles de votos por película.

**Decisión: IMDb es el punto de partida y los votos propios lo corrigen.** En lugar de arrancar toda película en el promedio global `C`, arranca en lo que dice IMDb de esa película:

1. **IMDb con su propio bayesiano**, para que cuente `imdb.votes` (un 9 con 40 votos no vale lo mismo que uno con 500.000):
   ```
   Q = (V·imdb.rating + M·6,67) / (V + M)
   ```
   `V` = `imdb.votes`; 6,67 = promedio de IMDb en el catálogo; `M` en los miles (con la mediana, ≈ 3.000).
2. **Pasar a la escala 1–5** con una regresión de los votos sobre `Q`: `Q₅ = a·Q + b`. Con `M = 3.000`, en la base limpia da `Q₅ = 0,53·Q − 0,17`, y se recalcula al indexar (3.4).
3. **Votos propios sobre IMDb**, la fórmula de 3.1 con `Q₅` en lugar de `C`:
   ```
   WR = (v·R + m·Q₅) / (v + m)
   ```
   Si la película no tiene IMDb (137 en el crudo), se usa `C`.

Ejemplos con los valores decididos, `M = 3.000` y `m = 5` (3.4), y el `Q₅` de la base limpia:

| Película | IMDb | Votos propios | `Q₅` | `WR` | Efecto |
| :-- | :-- | :-- | --: | --: | :-- |
| X | 8,5 con 500.000 votos | ninguno | 4,36 | 4,36 | Sin votos propios queda arriba; con 3.1 sola quedaría empatada en `C` |
| Y | 9,0 con 40 votos | ninguno | 3,41 | 3,41 | Con pocos votos en IMDb, casi no se le cree el 9 |
| Z | 7,0 con 20.000 votos | 10, promedio 4,8 | 3,54 | 4,38 | Los votos propios la suben |

El mismo `WR` es el que usa el piso de calidad `β·WR` de las recomendaciones personalizadas (4.3).

**Alternativas descartadas:**

| Alternativa | Por qué no |
| :-- | :-- |
| Solo IMDb | Los votos de la app no cambiarían el ranking: si los profesores votan, la portada sigue igual |
| Solo votos propios (3.1 tal cual) | Las 7.440 películas sin votos quedan empatadas en `C`, y el resto depende de 2 o 3 votos ruidosos |
| Promedio ponderado de dos rankings, `α·WR_propio + (1−α)·WR_imdb` | Agrega un peso `α` sin forma de justificarlo; la propuesta resuelve lo mismo sin él |

### 3.4 · Valores de `m` y `M` (R5)

- **`M`:** cuántos votos de IMDb hacen falta para creerle a su promedio.
- **`m`:** cuántos votos propios hacen falta para contradecir a IMDb.

**Medición:** en las 7.403 películas con 2 o más votos propios, se escondió la mitad de los votos (25.299, semilla 2026), se calculó `WR` con la otra mitad y se midió el error al predecir los escondidos (RMSE, menor es mejor):

| Predicción | RMSE |
| :-- | --: |
| Promedio global `C` para todas | 0,883 |
| Solo el promedio propio, sin IMDb | 0,778 |
| Solo IMDb, sin votos propios (`m = ∞`) | 0,751 |
| **IMDb + votos propios, `m = 5`** | **0,725** |

| `M` \ `m` | 1 | 2 | 5 | 10 | 20 | 50 |
| :-- | --: | --: | --: | --: | --: | --: |
| 0 | 0,7409 | 0,7311 | **0,7249** | 0,7262 | 0,7313 | 0,7396 |
| 1.000 | 0,7418 | 0,7327 | 0,7275 | 0,7294 | 0,7348 | 0,7433 |
| 3.000 | 0,7425 | 0,7341 | 0,7298 | 0,7322 | 0,7380 | 0,7468 |
| 10.000 | 0,7436 | 0,7361 | 0,7335 | 0,7370 | 0,7438 | 0,7533 |
| 30.000 | 0,7450 | 0,7390 | 0,7390 | 0,7447 | 0,7531 | 0,7642 |

- **`m = 5` (medido):** es el mejor con cualquier `M`. Con 5 votos propios, la película pesa mitad lo propio y mitad IMDb. Combinar las dos fuentes le gana a usar cualquiera sola, y eso confirma R4.
- **`M = 3.000` (por criterio):** el menor error es con `M = 0`, pero la diferencia contra 3.000 es del 0,7 %. Lo que sí cambia es la portada. Con `M = 0`, el top 10 incluye *The Real Miyagi* (9,3 con 41 votos en IMDb) y *A Brave Heart* (9,4 con 45) al lado de *The Godfather*. Con `M = 3.000` salen, y entran *The Decalogue*, *Pride and Prejudice* y *Cosmos*. El dataset prefiere `M = 0` porque los usuarios sintéticos parecen haber seguido a `imdb.rating` sin importar cuántos votos tenía (6.1), así que no sirve para decidir `M`. 3.000 es aproximadamente la mediana de `imdb.votes`.
- **El pasaje a 1–5 se recalcula al indexar:** es una regresión de los votos activos sobre `Q`, en cada `data.cleaned`, en lugar de números fijos en el código. Con `M = 3.000` da `0,53·Q − 0,17` en la base limpia (9.6) y `0,53·Q − 0,18` en el crudo, con una copia por `imdb.id`.
  - **Corrección (P2 de la implementación):** antes decía `0,48·Q + 0,18`. Es el mapeo del mejor punto de la grilla (`M = 0`), calculado con la mitad de los votos, que es lo que imprime `m_y_M.py`. Los ejemplos de 3.3 estaban hechos con ese mapeo y se recalcularon.

Reemplaza el análisis de 3.2 (`m` entre 5 y 15), que usaba `C` como punto de partida. Los números se recalculan sobre la base limpia.

### 3.5 · Presentación (R6, R7)

- **Filas por género (decidida):** en lugar de una sola lista, una fila por género ("Lo mejor en Comedia", "Lo mejor en Acción"), con el mismo ranking filtrado. Da variedad y facilita encontrar algo para votar. Después de la limpieza quedan 25 géneros.
- **Onboarding (decidido):** ver abajo.

#### Onboarding (R7)

**La pantalla:**

- Aparece cuando entra un usuario sin votos y sin géneros guardados. Se puede saltear, y los géneros se pueden cambiar después desde el perfil.
- Pide elegir **de 1 a 3 géneros**. Con más, la elección deja de decir algo.
- Ofrece **22 de los 25 géneros**. Quedan afuera Talk-Show (1 película), News (43) y Short (255), que es un formato (cortometraje) y no dice de qué trata la película. Film-Noir (101) queda adentro.

Películas por género en el crudo, una copia por `imdb.id`:

| Géneros | Películas |
| :-- | :-- |
| Drama · Comedy · Romance · Thriller · Crime · Action | 11.232 · 5.755 · 3.133 · 2.349 · 2.335 · 2.239 |
| Adventure · Documentary · Horror · Biography · Family · Mystery | 1.829 · 1.684 · 1.555 · 1.218 · 1.117 · 1.107 |
| Fantasy · Sci-Fi · History · Animation · Music · War | 971 · 919 · 835 · 763 · 725 · 665 |
| Musical · Sport · Western · Film-Noir | 405 · 341 · 247 · 101 |
| Excluidos: Short · News · Talk-Show | 255 · 43 · 1 |

**Efecto en la portada:**

| Situación | Portada |
| :-- | :-- |
| Sin géneros (salteó el onboarding) | Filas por género en el orden por defecto, de los más grandes a los más chicos |
| Con géneros, sin votos | Primero una fila "Para vos" con lo mejor (`WR`) dentro de sus géneros, y después sus géneros antes que el resto |
| Con votos | "Recomendadas para vos" pasa a ser por contenido (7.1); sus géneros siguen ordenando las filas |

**Los géneros elegidos no entran en el puntaje por contenido:** el gusto lo dan los votos (4.2). Los géneros solo ordenan qué se muestra primero.

**El recomendador no se entera de los géneros elegidos.** Devuelve el ranking `WR` de cada género, como ya estaba previsto (R6, R18). El `backend`:

- guarda los géneros del usuario en MongoDB (una colección nueva, por ejemplo `preferences`: `{user_id, genres}`);
- ordena las filas;
- arma "Para vos" juntando las listas de los géneros elegidos, sacando las repetidas y ordenando por `WR`. Si cada lista trae las 20 mejores de su género con su `WR`, las 20 mejores de la unión están seguro entre ellas, así que el resultado es exacto.

Así, el orden de la portada, que es presentación, queda en el `backend`, y el recomendador no depende de una colección ajena. Descartado: que el `backend` le pase los géneros al recomendador en cada petición, o que el recomendador los lea de MongoDB. Solo harían falta si los géneros entraran en el puntaje por contenido.

**Para acordar con el grupo:** la pantalla (`frontend`), y guardar los géneros y armar la portada (`backend`). No afecta el contrato de datos de la limpieza.

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

**Escalas y pesos (R9):** las tres señales no están en la misma escala, así que pesos iguales no dan la misma influencia. Medido en 20.000 pares de películas al azar (sin copias duplicadas):

| Señal | Media | Desvío | Percentil 99 | Pares con 0 |
| :-- | --: | --: | --: | --: |
| Plot | 0,134 | 0,096 | 0,376 | 0 % |
| Géneros | 0,266 | 0,300 | 1,000 | 51,1 % |
| Personas (TF-IDF) | 0,000 | 0,008 | 0,000 | 99,8 % |

- **Géneros varía tres veces más que el plot:** con pesos iguales, el orden lo decidirían casi solo los géneros, y compartir "Drama" pesaría más que tener una trama casi idéntica.
- **Personas es un bonus ocasional:** vale 0 casi siempre, pero cuando coincide salta mucho.

Por eso, primero se **calibra** cada señal a una escala comparable y recién después se eligen los pesos:

- **Calibración:** cada señal se divide por el valor típico (mediana) de la similitud con la 10.ª película más parecida según esa señal, o sea, por "cuánto vale un buen vecino". Medido en el crudo: plot 0,461, géneros 1,000 y personas 0,195. Así, un 1 significa lo mismo en las tres señales.
- **Tope a personas:** después de calibrar, su aporte se corta en 2, para que compartir a alguien muy raro no tape lo demás.
- **Pesos (decididos):** `w₁ = 0,2` (plot), `w₂ = 0,4` (géneros) y `w₃ = 0,4` (personas). Salen de la prueba de conjuntos escondidos, con un mínimo para el plot. El motivo está en 6.3.

La idea inicial era plot > personas > géneros. La prueba no la confirmó, pero tampoco puede medir lo que mejor hace el plot (ver 6.3).

**Plot:**

- Se usa `plot` y no `fullplot`. `plot` está en todas las películas; `fullplot` falta en unas 300 y es largo, y los modelos chicos cortan el texto (alrededor de 256 sub-palabras).
- El modelo y su uso se detallan en [4.4](#44--embeddings-del-plot-r14-r17).
- **Calidad del texto (medida en el crudo):** mediana de 28 palabras y el 90 % entre 12 y 39, así que entra entero en el modelo. No hay placeholders ("No plot available"). Hay 317 con menos de 10 palabras (1,6 %), pero igual dicen algo (*"Vampires terrorize a city in Norrbotten."*). El 30 % termina en "...": es el resumen de IMDb truncado, pero conserva las ~30 primeras palabras. Hay 12 textos repetidos en 24 películas distintas, todos legítimos (la serie *Up* de Apted, remakes). El 2,2 % tiene `è` (A13), casi siempre en nombres propios.
- **Es una señal significativa:** de 2.000 películas al azar, sus 10 vecinas por plot comparten al menos un género en el **71,1 %** de los casos, contra el **48,9 %** de 10 películas al azar. A ojo también tiene sentido: *Toy Story* → *Toys in the Attic*, *A Town Called Panic*; *Alien* → *Forbidden Planet*, *Ghost Ship*.

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

En "Películas similares a A", si a A le falta una señal, el término es igual contra todas las candidatas y el orden no cambia: la regla solo importa cuando la que no tiene la señal es la candidata. Pesos fijos también permite calcular los vecinos de cada película como un solo producto de matrices al indexar (R15).

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

**Punto medio:** un 3 fijo supone que todos usan la escala igual, y para quien pone 4 a casi todo, un 3 es una mala nota. Se usa el promedio del usuario, corregido hacia `C` como en 3.1: `(n·promedio_usuario + k·C) / (n + k)`. Sin esa corrección, un usuario nuevo con un solo voto tendría peso 0 y el perfil quedaría vacío.

**`k = 5` (decidido):** es cuántos votos hacen falta para creerle al promedio propio del usuario, y es lo que vota un profesor en los primeros minutos de la demo. Se fija por criterio, porque en el dataset los promedios por usuario van casi todos de 3,22 a 3,82 y no hay diferencias de escala para ajustarlo. Con `C = 3,525`:

| Usuario | Punto medio | Peso de un 5 | Peso de un 4 |
| :-- | --: | --: | --: |
| Nuevo, votó un solo 5 | 3,77 | +1,23 | — |
| 20 votos, promedio 4,5 (generoso) | 4,31 | +0,69 | −0,31 |
| 20 votos, promedio 3,0 (exigente) | 3,11 | +1,89 | +0,89 |

Al usuario nuevo el primer voto ya le arma el perfil; al generoso, un 4 le cuenta como "no tan bueno".

**Descartado:** usar como punto medio lo esperable para cada película (`Q₅`, como en la prueba B de 6.1). Un 4 a *The Godfather* daría peso negativo, y el perfil se alejaría de una película que al usuario le gustó.

**Cómo se calcula (R15):** el perfil no se arma como un vector. Cada voto aporta `peso × similitud` a los vecinos precalculados de esa película, y se recomiendan las candidatas con mayor suma, excluyendo las que ya votó (ver 7.1). Los pesos son los de la tabla de arriba.

**El gusto lo ponen los votos del usuario:** el plot, los géneros y las personas son el idioma en que se expresa, y los votos deciden hacia dónde apunta el perfil. Dos usuarios que votan distinto reciben recomendaciones distintas. Los votos de los demás usuarios no cambian las recomendaciones de uno, salvo por el piso de calidad (4.3).

### 4.3 · Ajuste final de la lista (R19)

- **Piso de calidad, `β = 0,2`:** al puntaje se le suma `β·WR`, con el `WR` estandarizado (restada la media del catálogo y dividido por su desvío, 0,37 estrellas). Cada desvío de calidad vale 0,2 puntos de parecido calibrado. Así la cercanía al perfil no saca películas malas: con `β = 0`, lo recomendado tiene un `WR` promedio de 3,37, casi el del catálogo (3,41); con `β = 0,2`, 3,64.
- **Diversidad (MMR), `λ = 0,8`:** las recomendaciones se eligen de a una. Cada candidata vale `λ·puntaje − (1 − λ)·(su mayor similitud con las ya elegidas)`. Los dos términos se normalizan a 0–1, y la similitud es la misma de 4.1. Evita devolver diez películas casi iguales, por ejemplo tres secuelas seguidas de la misma saga.

Los dos valores salen de la prueba de conjuntos escondidos (6.3).

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

**Decisión (R17): embeber en paralelo con la limpieza.**

No cambia el resultado: el vector de un plot es `f(texto)` y no depende de los demás plots ni de cuántas películas haya, así que embeber todas las copias o solo las activas da los mismos vectores para las activas. Lo que sí depende del conjunto de películas (TF-IDF de personas, vecinos, `WR`) se calcula después de `data.cleaned`, solo con las activas.

- Al arrancar, el `recommender` lee los `plot` crudos y los embebe sin esperar `data.cleaned`. Puede hacerlo porque la limpieza no modifica `plot`: no hay ninguna regla sobre ese campo (ANOMALIAS, sección 6).
- **La clave es un hash del texto, no el `_id`.** Al fusionar duplicados, cada campo se toma de la copia más reciente que lo tenga válido (ANOMALIAS, A5), así que el `plot` de la ganadora puede venir de una copia perdedora. Pasa en 2 de los 651 grupos (*Little Fugitive*, *The Personals*). Como se embeben los plots de todas las copias, el plot ganador siempre está.
- Al recibir `data.cleaned`, se busca el vector de cada película activa por el hash de su `plot`. Si no está (un plot nuevo o modificado), se embebe en el momento.
- **Los vectores se guardan en un volumen del `recommender` (decidido)**, indexados por el hash del plot, para que el segundo arranque no embeba de nuevo. En MongoDB no, porque el `recommender` solo lee de ahí. Solo se guardan los embeddings: los vecinos, el TF-IDF y el `WR` dependen de los datos limpios y se recalculan en cada indexado (≈ 15–20 s).
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

## 6. Evaluación (R13)

### 6.1 · Los votos del dataset no reflejan gustos

**Prueba de dejar una afuera:** para cada usuario se esconde una película que le gustó y se mira si, según una señal, se parece más a sus otras películas que le gustaron o a las que no. Se repite con cada película que le gustó a cada usuario (~25.000 veces). Una señal que no sabe nada de los gustos acierta el 50 %, como una moneda. Se excluyen los pares de copias duplicadas (mismo `imdb.id`).

Se corrió dos veces:

- **A. Votos tal cual:** "le gustó" = 4 o 5 estrellas; "no le gustó" = 1 o 2.
- **B. Votos corregidos por calidad:** a cada voto se le resta lo que cualquiera le pondría a esa película según su IMDb (`esperado = 0,49 × imdb + 0,14`, ajustado con todos los votos). La diferencia es el gusto personal: un 3 a *The Godfather* (IMDb 9,2, esperado 4,6) da −1,6, y un 4 a una de terror de IMDb 5 (esperado 2,6) da +1,4. "Le gustó" = el cuarto de sus votos con mayor diferencia; "no le gustó" = el cuarto con menor.

| Señal | A. Votos tal cual | B. Corregidos por calidad |
| :-- | --: | --: |
| Cercanía en `imdb.rating` (sin contenido) | 84,2 % | 53,0 % |
| Plot | 49,0 % | 50,2 % |
| Géneros | 59,1 % | 49,0 % |
| Personas | 81,1 % | 47,1 % |

- **En A**, personas y géneros parecen funcionar, pero es la calidad colándose: los votos siguen a IMDb (correlación 0,53), y un mismo director suele tener varias películas de IMDb parecido. Solo la cercanía de IMDb, sin mirar el contenido, ya acierta el 84 %.
- **En B**, con la calidad descontada, las cuatro señales caen a ≈ 50 %: lo que queda en los votos es ruido.
- Coincide con otros dos datos: los promedios por usuario van casi todos de 3,22 a 3,82 (percentiles 5 y 95), y los usuarios no se concentran en ningún género. El 50 % de sus votos cae en su género más votado, contra el 59 % de un usuario que elige películas al azar.

**Lectura:** los usuarios del dataset puntúan según la calidad de la película más ruido, sin gustos propios. Parecen sintéticos, y las reseñas también (*"A well-earned 4 stars"*). Es una inferencia: el dataset no lo dice.

**Qué no cambia:** el plot sigue siendo una señal significativa (4.1), y con usuarios reales, como los profesores en la demo, el perfil (4.2) refleja sus gustos.

### 6.2 · Para qué sirven entonces los votos del dataset

| Uso | ¿Sirve? |
| :-- | :-- |
| Calidad: promedio bayesiano (R2), valor de `m` (R5), combinación con IMDb (R4), piso `β·WR` (4.3) | **Sí**: los votos siguen a la calidad |
| Gustos: ajustar `w₁`, `w₂`, `w₃` (R9) y mostrar que el contenido le gana a la popularidad | **No**: no hay gustos que encontrar |

La evaluación propuesta antes (división temporal por usuario, popularidad contra contenido, con precision@10 y NDCG@10) sigue sirviendo para la parte de calidad. Para la parte de gustos daría una conclusión engañosa: la popularidad ganaría, y no porque el contenido sea malo, sino porque estos votos no tienen gustos.

### 6.3 · Evaluación de gustos: conjuntos escondidos (R13)

Como los votos del dataset no tienen gustos, se arman casos donde se sabe de antemano qué debería recomendarse:

1. Se toma un conjunto de películas que "van juntas".
2. Se crea un usuario ficticio que vota 3 de ellas con 5 ★.
3. Se mide qué parte del resto del conjunto aparece en sus 20 primeras recomendaciones (recall@20).
4. Se repite con muchos conjuntos y con distintas combinaciones de pesos (R9). Se eligen los pesos que mejor dan en todos los tipos de conjunto.

**Se mezclan varios tipos de conjunto,** porque cada uno favorece a una señal. Con un solo tipo, la prueba elegiría siempre los pesos de esa señal. Se usaron tres:

| Tipo | Cómo se arma | Conjuntos |
| :-- | :-- | --: |
| Director | Películas del mismo primer director, si tiene 6 o más | 200 (de 647) |
| Saga | Títulos con la misma base (*X-Men*, *X-Men 2*, *X-Men: First Class*…) | 51 |
| Géneros | Películas con la misma combinación de 3 o más géneros, si son entre 6 y 40 | 161 |

**Limitación:** mide coherencia (que recomiende "lo del mismo tipo"), no si a una persona le gusta lo recomendado. Es lo más cercano que se puede medir sin usuarios reales.

#### Resultados

Medido sobre el crudo sin copias duplicadas (19.145 películas). Cada usuario ficticio vota 3 películas al azar de su conjunto, y se recomienda con los vecinos precalculados (7.1). La prueba completa tarda alrededor de un minuto.

**1. Pesos (sin `β` ni MMR).** Se probó toda la grilla de pesos con paso 0,1:

| Pesos (plot · géneros · personas) | Recall@20 | Director | Saga | Géneros |
| :-- | --: | --: | --: | --: |
| 0,1 · 0,4 · 0,5 (el mejor de la grilla) | 94,9 % | 95,4 | 93,0 | 96,2 |
| 0,0 · 0,5 · 0,5 | 94,6 % | 92,2 | 92,2 | 99,4 |
| **0,2 · 0,4 · 0,4 (elegido)** | **89,0 %** | 88,2 | 93,0 | 85,8 |
| ⅓ · ⅓ · ⅓ | 75,0 % | 79,7 | 92,4 | 52,7 |
| Solo personas | 63,9 % | 99,3 | 88,0 | 4,5 |
| Solo géneros | 39,7 % | 1,5 | 17,6 | 100 |
| Solo plot | 26,3 % | 2,5 | 72,8 | 3,5 |

**Por qué se eligió 0,2 · 0,4 · 0,4 y no el mejor de la grilla:**

- **La prueba no puede medir lo que mejor hace el plot.** Los conjuntos "director" se definen con el campo `directors`, así que los encuentra la señal de personas (99 %). Los conjuntos "géneros" se definen con `genres`, así que los encuentra la señal de géneros (100 %). Ningún tipo de conjunto se define por **de qué trata** la película, por ejemplo "películas de atracos" de gente distinta y con géneros distintos. Eso es justo lo que aporta el plot, y es la única señal que generaliza (4.1).
- **No se puede armar ese tipo de conjunto sin trampa.** El dataset no trae nada que diga "estas dos tratan del mismo tema" salvo el propio plot, y usarlo para armar la prueba la haría a favor del plot.
- **Por eso al plot se le aplica el mismo criterio que a `β` y a `λ`:** el mayor peso que conserve al menos el 90 % del recall máximo (≥ 85,4 %). Es 0,2: la mejor combinación con ese peso es 0,2 · 0,4 · 0,4, con 89,0 %. Con plot 0,3 la mejor combinación llega solo al 78,1 % (0,3 · 0,4 · 0,3), y con 0,4, al 68,7 %.
- **Aun así el plot hace falta:** solo, recupera el 72,8 % de las sagas, casi sin ayuda de géneros. Y es la única señal de las 7 películas sin géneros ni personas compartidas (4.1).

**2. Piso de calidad `β`, con los pesos elegidos y sin MMR.** Se eligió el mayor `β` que conserva al menos el 90 % del recall sin `β` (≥ 80,1 %):

| `β` | Recall@20 | `WR` promedio de lo recomendado |
| --: | --: | --: |
| 0 | 89,0 % | 3,37 |
| 0,1 | 87,7 % | 3,54 |
| **0,2** | **85,1 %** | **3,64** |
| 0,3 | 79,9 % | 3,74 |
| 0,5 | 68,6 % | 3,86 |

El "`WR` promedio de lo recomendado" es el promedio del `WR` de las 20 recomendaciones: mide qué tan buenas son en general (el catálogo promedia 3,41). `β = 0,2` sube la calidad de lo recomendado de 3,37 a 3,64 y pierde 3,9 puntos de recall. `β = 0,3` ya no llega al 90 %.

**3. Diversidad (MMR), con los pesos elegidos y `β = 0,2`:**

| `λ` | Recall@20 | Similitud interna de la lista |
| --: | --: | --: |
| 1,0 (sin MMR) | 85,1 % | 0,218 |
| 0,9 | 84,8 % | 0,217 |
| **0,8** | **83,5 %** | **0,215** |
| 0,7 | 81,6 % | 0,211 |
| 0,6 | 80,8 % | 0,204 |

La "similitud interna" es el coseno promedio entre los plots de los 190 pares de películas de la lista de 20. Más bajo significa una lista más variada.

**Por qué se eligió `λ = 0,8`:** el criterio del 90 % habría permitido bajar hasta 0,6. Pero con estos números la diversidad que se gana es chica (0,218 → 0,204) y el recall cae 4,3 puntos. Con 0,8 se pierden 1,6 puntos y MMR queda como protección para los casos que la prueba no mide, como un usuario que vota varias películas de una misma saga.

**Ojo con la medida de diversidad:** la similitud interna se midió solo con el plot, mientras que MMR penaliza con la similitud combinada (4.1). Si MMR evita sobre todo "otra más del mismo director", esta medida no lo ve y su beneficio puede estar subestimado.

**Resultado final: `w = (0,2 · 0,4 · 0,4)`, `β = 0,2`, `λ = 0,8`, con recall@20 de 83,5 %.**

La prueba también imprime algunas listas de ejemplo ("votó 3 de un director → recomienda esto"), que sirven para el informe sin trabajo extra.

**Descartadas por tiempo:** revisar a mano perfiles armados a propósito, y un estudio con personas reales votando y puntuando recomendaciones. La evaluación no tiene intervención humana.

## 7. Integración con la arquitectura

- **Filtrar `deleted: true`** en `movies` y en `reviews` (ANOMALIAS, G1). Si no, se recomiendan copias duplicadas y cuentan votos anónimos, huérfanos o repetidos.
- **Aclaraciones del contrato:** acordadas con el grupo y registradas en [ANOMALIAS, sección 7](../analysis/ANOMALIAS.md#aclaraciones-acordadas-2026-11-19). Para el recomendador implican:
  - Filtrar con `deleted: false`, porque el campo siempre está.
  - Todo voto activo tiene `rating` de 1 a 5.
  - Todo voto activo apunta a una película activa.
  - `directors`, `cast` y `writers` que faltan se tratan como listas vacías.
  - El `plot` se puede embeber antes de que termine la limpieza (R17).
- **Votos nuevos:** llegan a MongoDB por `ingest-consumer`. En cada petición se leen los votos del usuario con una consulta indexada por `user_id`, así que un voto propio se refleja en la siguiente petición, sin reentrenar.

### 7.1 · Vecinos precalculados (R15)

El enunciado de la cátedra pide que ninguna petición calcule similitudes contra todo el catálogo (README, "Recomendaciones"). Por eso, la similitud contra todo el catálogo se calcula **una sola vez, al indexar**, y la petición solo lee lo guardado.

| Momento | Qué se hace |
| :-- | :-- |
| **Al indexar** (al recibir `data.cleaned`) | Para cada película, se calcula su similitud (4.1) contra todo el catálogo y se guardan en memoria sus **100** más parecidas, con el puntaje. Dependen solo del contenido: los votos nuevos no las cambian |
| **"Recomendadas para vos"** | Se leen las listas de las películas que votó el usuario. Cada candidata suma `peso del voto × puntaje guardado` por cada lista en la que aparece. Se suma `β·WR`, se aplica MMR entre las candidatas y se devuelven las primeras |
| **"Películas similares"** | La lista guardada de esa película, reordenada con `β·WR` y MMR |

**Ejemplo** (puntajes ilustrativos): con *Heat* a 5 ★ (peso +2), *Ocean's Eleven* a 4 ★ (+1) y *Titanic* a 1 ★ (−2), *The Town* aparece en las listas de *Heat* (0,55) y de *Ocean's Eleven* (0,40) y suma 2·0,55 + 1·0,40 = 1,50. *Ronin*, solo en la de *Heat* (0,62), suma 1,24. *The Notebook*, en la de *Titanic* (0,65), suma −1,30 y se descarta.

**Casos especiales:**

- **Solo votos negativos** (o ningún voto por encima del punto medio): se muestra el ranking de usuario nuevo (3), sin lo que votó y sin los vecinos de lo que no le gustó.
- **Menos de 10 candidatas positivas:** se completa con el ranking de usuario nuevo.
- **MMR:** se calcula solo entre las candidatas (≈ 200), no contra el catálogo.

**Medido** (PC con Windows, 4 CPUs; 300 usuarios reales del dataset, mediana de 25 votos):

| | Producto contra todo el catálogo | Vecinos precalculados |
| :-- | --: | --: |
| "Recomendadas para vos", mediana / p95 | 11 / 30 ms | 8 / 19 ms |
| Costo extra al indexar | — | ≈ 15 s; 16 MB con K = 100 |

Los dos entran en el objetivo de < 100 ms; lo que decide es la regla del enunciado. Una matriz de similitud completa (20.000 × 20.000) no entraría en memoria: ocupa unos 1,6 GB.

**Diferencia con comparar contra todo el catálogo:** las parejas que no están en ninguna lista cuentan 0. Por eso:

- se recomienda lo que se parece **mucho a alguna** película votada, no lo que se parece **un poco a todas**;
- un voto negativo solo hunde a sus vecinos, no aleja de un estilo en general;
- se puede explicar en la interfaz: "porque te gustó *Heat*".

Con la misma fórmula y sin `β`, el top 10 coincide en un 99,9 % con un solo voto, y en un 12 % con todos los votos del usuario. Subir K de 50 a 200 casi no cambia esa coincidencia: la diferencia viene de lo que mide cada método, no de que falten candidatas. Con K = 50 ya hay una mediana de 634 candidatas por usuario; 100 deja margen sin costo apreciable.

### 7.2 · Actualización del `WR` (R18)

El ranking de usuario nuevo y el piso `β·WR` dependen de los votos de todos. Si se calcularan una sola vez al indexar, los votos nuevos no moverían la portada, y ese era el motivo para combinar con IMDb (R4). Recalcularlo en cada petición iría contra la regla.

**Decisión:** se recalcula en segundo plano cada 60 segundos, agregando los votos activos en MongoDB (≈ 60.000), fuera de toda petición. Un voto nuevo se refleja en la portada en menos de un minuto.

## 8. Campos que usa el recomendador

Responde al pendiente 1 de ANOMALIAS ("¿Qué campos de `movies` usan la ficha y el recomendador?"):

| Colección | Usa | No usa |
| :-- | :-- | :-- |
| `movies` | `plot`, `genres`, `directors`, `cast`, `writers`, `imdb.rating`, `imdb.votes`, `deleted` | `fullplot`, `tomatoes`, `awards`, `metacritic`, `released`, `rated`, `runtime`, `year` |
| `reviews` | `user_id`, `movie_id`, `rating`, `deleted` | `comment`, `date` (solo para la evaluación) |

Para el recomendador, `tomatoes` puede quedar sin corregir. La ficha puede necesitar otros campos.

## 9. Especificación para implementar

Junta en un solo lugar lo decidido en las secciones anteriores, con el detalle que hace falta para programarlo. La referencia ejecutable es [analysis/recomendador/pesos.py](../analysis/recomendador/pesos.py): implementa los pasos 2 a 6 de 9.2 y la recomendación de 9.3, y sirve para comparar los resultados del servicio.

### 9.1 · Parámetros

| Parámetro | Valor | Dónde se decidió |
| :-- | :-- | :-- |
| Modelo de embeddings | `sentence-transformers/all-MiniLM-L6-v2` con `fastembed` (ONNX), 384 dimensiones | 4.4 (R14) |
| Pesos `w₁`, `w₂`, `w₃` (plot, géneros, personas) | 0,2 · 0,4 · 0,4 | 6.3 (R9) |
| Tope del aporte de personas, ya calibrado | 2,0 | 4.1 |
| Calibración | Mediana del 10.º vecino de cada señal, sobre 1.000 películas al azar (semilla fija); se excluyen las que no tienen 10 vecinos con similitud > 0 | 4.1 |
| Vecinos por película `K` | 100 | 7.1 (R15) |
| Candidatas antes de MMR | 200 | 7.1 |
| `m` (votos propios) | 5 | 3.4 (R5) |
| `M` (votos de IMDb) | 3.000 | 3.4 (R5) |
| `k` (punto medio del usuario) | 5 | 4.2 (R10) |
| Piso de calidad `β` | 0,2, sobre el `WR` estandarizado | 4.3 (R19) |
| MMR `λ` | 0,8 | 4.3 (R19) |
| Candidatas positivas que no alcanzan | Se completa con el ranking global hasta llegar a `limit` | 7.1 |
| Recálculo del `WR` | Cada 60 s | 7.2 (R18) |

Los demás números (`C`, promedio de `imdb.rating`, `a` y `b` de `Q₅`, escalas de calibración, media y desvío del `WR`) **no se fijan en el código**: se calculan con los datos activos al indexar, o cada 60 s en el caso del `WR`.

### 9.2 · Al arrancar y al indexar

Todo el cálculo pesado corre fuera del event loop (`run_in_executor`), para que `/health` siga respondiendo (esqueleto, regla del event loop). Las estructuras nuevas reemplazan a las anteriores de una sola vez, al terminar.

1. **Embeddings (al arrancar, sin esperar `data.cleaned`, R17):**
   - Se cargan del volumen los vectores ya calculados: hash SHA-256 del texto del `plot` → vector.
   - Se leen los `plot` de todas las películas, activas o no, y se embeben los que falten.
   - Se guarda el volumen.
   - El modelo viene en la imagen: se descarga en un `RUN` del Dockerfile.
2. **Datos (al recibir `data.cleaned`, o al arrancar con la marca `done`):**
   - Se leen las películas con `deleted: false`, con los campos de la sección 8.
   - Se leen los votos con `deleted: false`.
   - Si falta el vector de algún plot, se embebe en ese momento.
3. **Señales**, una fila por película y cada fila normalizada a largo 1:
   - **Plot:** el embedding.
   - **Géneros:** una posición por género (1 si lo tiene). Sin géneros, una fila de ceros.
   - **Personas:**
     - se juntan `directors`, `cast` y `writers` (las listas que faltan cuentan como vacías);
     - se quita el rol con `re.sub(r"\s*\(.*$", "", nombre).strip()`;
     - se descartan los nombres que aparecen en una sola película;
     - cada nombre pesa `log(N / df)`, donde `N` es la cantidad de películas activas y `df` es en cuántas aparece ese nombre;
     - la matriz es dispersa.
4. **Calibración:** para cada señal, con 1.000 películas al azar:
   - se calcula su similitud (producto escalar) contra todo el catálogo, sin contarse a sí misma;
   - se toma el 10.º valor más alto;
   - se guarda la mediana de los que son mayores que 0. Son `q_plot`, `q_géneros` y `q_personas`.
5. **Vecinos**, en bloques de 1.000 películas para no armar la matriz completa:
   ```
   S = 0,2·(P·Pᵀ)/q_plot + 0,4·(G·Gᵀ)/q_géneros + 0,4·min((T·Tᵀ)/q_personas, 2)
   ```
   - Se excluye la propia película.
   - Se guardan las 100 de mayor `S`: ids en `int32` y puntajes en `float32`.
   - Tarda ≈ 15–20 s y ocupa 16 MB.
6. **`WR`** (3.3), que después se recalcula cada 60 s con los votos activos:
   - `C` = promedio de los votos activos.
   - `Q = (V·imdb.rating + 3000·Ī) / (V + 3000)`, con `V = imdb.votes` e `Ī` = promedio de `imdb.rating` en el catálogo. Si falta `imdb.rating` o `imdb.votes`, no hay `Q`.
   - `a` y `b`: regresión lineal de cada voto activo sobre el `Q` de su película, solo para las que tienen `Q`.
   - `prior = a·Q + b`, o `C` si la película no tiene `Q`.
   - `WR = (suma de sus votos + 5·prior) / (cantidad de votos + 5)`.
   - `WRz = (WR − media) / desvío`, con la media y el desvío sobre el catálogo activo.
   - **Rankings:** uno global y uno por género, ordenados por `WR`.
7. `/health` pasa a `ready: true`.

### 9.3 · Por petición

**"Recomendadas para vos"** (7.1):

1. Se leen los votos activos del usuario: `reviews` con su `user_id` y `deleted: false`. Ya hay un índice por `user_id` (`dataset/mongo-init.sh`).
2. **Sin votos:** se devuelve el ranking global, con `source: "ranking"`.
3. `punto medio = (suma de sus estrellas + 5·C) / (cantidad de votos + 5)`, y cada voto pesa `estrellas − punto medio`.
4. Para cada película votada `i` y cada vecina `j` de su lista, si `j` no fue votada: `acc[j] += peso_i × S_ij`.
5. **Ningún voto con peso positivo:** se devuelve el ranking global, sin las votadas ni las vecinas de las votadas.
6. Candidatas: las 200 de mayor `acc`, solo con `acc > 0`.
7. `puntaje = acc + 0,2·WRz`.
8. **MMR**, para elegir de a una hasta `limit`:
   - cada candidata vale `0,8·puntaje_n − 0,2·(su mayor similitud_n con las ya elegidas)`;
   - `puntaje_n` es el puntaje llevado a 0–1 (mín–máx) entre las candidatas;
   - `similitud_n` es `S` (fórmula de 9.2) entre las candidatas, dividida por su máximo. Son ≈ 200 × 200: no es contra el catálogo.
9. **Candidatas que no alcanzan para `limit`:** se completa con el ranking global, sin repetir y sin las votadas. Generaliza el caso de 7.1, "menos de 10".
10. **Motivo de cada recomendada:** la película votada que más aportó a su `acc` ("porque te gustó *Heat*").

**"Películas similares a A":** se toma la lista de vecinas de A, con `puntaje = S + 0,2·WRz` y MMR como en el paso 8. Si A no está activa, se responde 404.

**Rankings:** se leen los ya calculados, porque no dependen del usuario.

### 9.4 · API para el `backend` (implementada; la forma sigue a acordar con el grupo)

El `backend` le pide al `recommender` solo identificadores (README, "Recomendaciones") y completa la ficha desde MongoDB. Todo es HTTP interno en el puerto 8000: el `recommender` está solo en `internal-net`, sin puerto publicado, así que el `frontend` no lo alcanza. Está en [services/recommender/app/api.py](../services/recommender/app/api.py).

| Endpoint | Parámetros | Respuesta |
| :-- | :-- | :-- |
| `GET /users/{user_id}/recommendations` | `limit` (20 por defecto, máximo 100) | `{"source": "content" \| "ranking", "items": [{"movie_id", "score", "because": movie_id \| null}]}` |
| `GET /movies/{movie_id}/similar` | `limit` (10 por defecto, máximo 100) | `{"items": [{"movie_id", "score"}]}`; 404 si la película no está activa |
| `GET /rankings` | `genre` (opcional; sin él, el global), `limit` (20 por defecto, máximo 100) | `{"genre": … \| null, "items": [{"movie_id", "wr"}]}`; 404 si el género no existe |
| `GET /genres` | — | `{"items": [{"genre", "movies"}]}`: los géneros con su cantidad de películas activas, para las filas y el onboarding |
| `GET /health` | — | El de siempre, con `ready` (esqueleto) |

- **Sin terminar de indexar**, los cuatro primeros responden **503** con `{"detail", "phase"}` y `Retry-After: 5`. `phase` es `embedding`, `waiting-cleaning` o `indexing`. El `backend` ya distingue ese estado por `GET /status` (`indexing`). Al reindexar no hay 503: se responde con el índice anterior.
- **Sin MongoDB**, solo `/users/{id}/recommendations` responde 503 (`"MongoDB no disponible"`), después de ≈ 3 s de espera, el `serverSelectionTimeoutMS` del helper común. Las demás rutas leen solo de memoria y siguen respondiendo.
- **`limit`** fuera de 1–100, o que no es un número: **422**, la validación de FastAPI.
- **`movie_id`** es el `_id` de la película como string hexadecimal. Una copia fusionada como duplicada da 404: el `backend` puede seguir su `mergedInto`.
- **`because`** sirve para mostrar en la interfaz "porque te gustó…".
- **Usuario sin votos:** `/users/{id}/recommendations` responde el ranking global (`source: "ranking"`). La fila "Para vos" del onboarding la arma el `backend` con `/rankings?genre=…` (3.5).
- **El onboarding usa 22 géneros:** el `backend` saca de `/genres` los que no se ofrecen (Talk-Show, News, Short).

### 9.5 · Volumen, dependencias y evaluación

- **Volumen:** uno nombrado (por ejemplo `recommender-cache`), con los embeddings por hash del plot. Nada más, porque lo demás se recalcula en cada indexado (4.4).
- **Dependencias:** `fastembed`, `numpy` y `scipy`. Las versiones con las que se midió están en [analysis/recomendador/requirements.txt](../analysis/recomendador/requirements.txt).
- **Evaluación:** los scripts de [analysis/recomendador](../analysis/recomendador/) reproducen cada número de este documento. Con la base limpia hay que correr de nuevo `pesos.py` y `m_y_M.py`, leyendo de MongoDB en vez de los `.json.gz` (pendiente 7).

### 9.6 · Implementación (2026-11-20)

El código está en [services/recommender/app](../services/recommender/app/):

| Módulo | Qué hace |
| :-- | :-- |
| `model.py` | El modelo de embeddings. Se descarga en el `RUN` del Dockerfile y se carga sin red |
| `embeddings.py` | La caché de vectores por hash del plot, en el volumen `recommender-cache` |
| `index.py` | Pasos 3 a 6 de 9.2: señales, calibración, vecinos y `WR`. Funciones puras |
| `recommend.py` | 9.3: "para vos", similares y rankings. Funciones puras |
| `store.py` | Las lecturas de MongoDB. Los votos se agregan en Mongo, con una fila por película |
| `lifecycle.py` | Las tareas de fondo: embeber, esperar la limpieza, indexar y recalcular el `WR` cada 60 s |
| `api.py` | Las rutas de 9.4 |

**Ciclo de vida:**
- **Arranque:**
  - El `recommender` se suscribe a `recommender.data-cleaned` **antes** de leer la marca de limpieza.
  - Indexa cuando se cumplen dos condiciones: los embeddings terminaron, y la marca dice `done` o llega un mensaje.
- **Mensajes repetidos:** se juntan en un indexado, o en uno más si llegan mientras indexa.
- **El mensaje es solo un aviso:** se confirma al llegar y no se lee su contenido. Lo que vale es la marca.
- **La marca** es la que escribe el `cleaning-agent`: `{_id: "state", status}` en la colección `cleaning`. Sus nombres están en [libs/common/dcicflix_common/cleaning.py](../libs/common/dcicflix_common/cleaning.py).
- **`/health`** agrega `ready`, que significa "hay índice", `phase`, `movies` y `votes`. Las fases son:

  ```
  embedding → waiting-cleaning → indexing → ready      (al reindexar: ready + indexing)
  ```

**Medido en Docker** (Windows, Docker Desktop, 4 CPUs):

| Qué | Valor |
| :-- | :-- |
| Imagen | 694 MB, con el modelo adentro; el build tarda ≈ 160 s |
| Primer embedding, con el volumen vacío | 448–477 s para 19.135 plots distintos de 19.842 (en el host, 4.4: 376 s) |
| Arranque con la caché completa | 0 plots embebidos; los embeddings están listos en < 1 s |
| Indexado sobre la base limpia | 16–19 s, casi todo en armar el catálogo: vecinos y calibración. Hasta ≈ 44 s cuando la PC estaba ocupada con otras pruebas |
| Memoria | 181 MiB sin índice y 354 MiB con índice. El modelo se carga solo mientras embebe: cargado ocupa 1,28 GiB |
| `/health` mientras embebe o indexa | 3–148 ms |
| "Para vos", 300 usuarios, desde el `backend`: red, Mongo y cálculo | mediana 10–11 ms, p95 42–47 ms (objetivo del README: < 100 ms). Justo después de reiniciar Mongo, con su caché fría: 20,7 / 86,2 ms |
| "Similares", 300 películas, desde el `backend` | mediana 5,4 ms, p95 36,1 ms |
| Un voto nuevo | Cambia "para vos" en la petición siguiente; el `WR` y los rankings, en ≤ 60 s |

**Contra la referencia** ([comparar_servicio.py](../analysis/recomendador/comparar_servicio.py), que corre `index.py` y `recommend.py` sobre el crudo con los vectores del contenedor):
- **Recall@20:** 83,7 % contra 83,5 % de `pesos.py` (6.3). `pesos.py` con esos mismos vectores da exactamente 83,5 %, así que el modelo del contenedor produce los mismos vectores que el de la medición.
- **Calibración:** con la misma muestra da lo mismo que `pesos.py` (0,461 / 1,000 / 0,195).

**Sobre la base limpia** (19.141 películas activas, 701 fusionadas):
- 58.322 votos válidos;
- `C = 3,527`;
- `Q₅ = 0,53·Q − 0,17`;
- `WR` con media 3,41 y desvío 0,37.

El único valor fuera de contrato que queda son **1.884 reseñas activas con `rating: null`**: sin `LLM_API_KEY`, el `cleaning-agent` no infiere las estrellas del comentario (pendiente 10). El `recommender` las descarta como votos y las cuenta en el log.

**Fallas probadas:**

| Falla | Comportamiento |
| :-- | :-- |
| `stop` a mitad del embedding | Termina el lote en curso, guarda y sale en ≈ 1 s. Al volver, retoma desde lo guardado |
| `stop` a mitad del indexado | El hilo que arma el catálogo no se puede cortar, y el proceso espera a que termine. En esta PC Docker manda SIGKILL ≈ 3 s después del SIGTERM, así que el contenedor sale con 137. Con `-t 30` sale con 0 a los ≈ 11 s. No se pierde nada, porque el indexado no escribe nada duradero, y al volver indexa de nuevo |
| Se cae RabbitMQ | `/health` da 503 hasta que vuelve, pero la API sigue respondiendo desde la memoria. aio-pika restaura la cola y el consumidor: un `data.cleaned` posterior reindexa |
| Se cae MongoDB con el índice listo | "Para vos" da 503 a los ≈ 3 s; el resto sigue respondiendo. El recálculo del `WR` conserva el anterior. Al volver Mongo se recupera solo |
| Se cae MongoDB durante un indexado | La lectura reintenta cada ≈ 8 s (3 s del timeout más 5 s de espera) y el indexado termina ≈ 3 s después de que vuelve Mongo. Mientras tanto responde el índice anterior |

**Bugs encontrados:**
- **Hashes recortados:** numpy recortaba los `\x00` del final de los hashes guardados como `S32`, y 1 de cada 256 hashes SHA-256 termina en `\x00`. Por eso 78 plots se volvían a embeber en cada arranque. Ahora se guardan como una matriz `uint8` de n × 32, y al cargar se valida el formato.
- **Calibración de `pesos.py`:** toma `-np.partition(-x, 10)[:, 9]`, que no es exactamente el 10.º valor más alto. Con el exacto, la escala de personas da 0,193 en vez de 0,195. El servicio usa el exacto, y la diferencia no cambia los resultados.

## 10. Pendientes

1. ~~Combinación con IMDb (R4)~~: decidida en 3.3.
2. ~~Valores de `m` y `M` (R5)~~: decididos en 3.4. `k = 5` (R10).
3. ~~Onboarding (R7) y filas por género (R6)~~: decididos en 3.5. Falta acordar con el grupo la parte del `frontend` y del `backend`.
4. ~~Embeber en paralelo con la limpieza (R17)~~: decidido. Saber cuánto tarda la limpieza queda como sugerencia para el `cleaning-agent` (ANOMALIAS, pendiente 4).
5. ~~Vecinos precalculados o producto por petición (R15)~~: vecinos precalculados, en 7.1. El `WR` se recalcula cada 60 s (R18, 7.2).
6. ~~Calibración y pesos (R9), `β` y `λ` (R19)~~: decididos en 4.1, 4.3 y 6.3.
7. Recalcular sobre la base limpia los números de la sección 2, `m` y `M` (3.4) y la prueba de conjuntos escondidos (6.3). No deberían moverse mucho; si se mueven, se revisan los valores. **Avance:** lo que calcula el servicio al indexar ya está medido sobre la base limpia, y coincide con el crudo (9.6): `C`, `Q₅` y la media y el desvío del `WR`. Faltan los scripts, que siguen leyendo los `.json.gz`.
8. ~~Guardar los vectores en un volumen~~: decidido en 4.4, solo los embeddings.
9. Acordar con el grupo la API de 9.4 (`backend`) y las pantallas del onboarding (`frontend`). La API ya está implementada como la describe 9.4.
10. **`rating: null` sin LLM:** el contrato de ANOMALIAS dice que `reviews.rating` es un `int` de 1 a 5, pero sin `LLM_API_KEY` quedan 1.884 reseñas activas con `null`. Hay que acordar con el `cleaning-agent` si el contrato admite `null` en ese caso. El `recommender` ya las descarta, así que no necesita cambios.
