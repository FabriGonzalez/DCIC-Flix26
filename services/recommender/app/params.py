"""Parámetros del recomendador (docs/recomendador.md 9.1). Solo los decididos.

Lo que sale de los datos (C, promedio de imdb.rating, a y b de Q₅, escalas de
calibración, media y desvío del WR) no está acá: se calcula al indexar, o cada
WR_REFRESH segundos en el caso del WR.
"""

# Pesos de las tres señales, ya calibradas (R9, 6.3).
W_PLOT = 0.2
W_GENRES = 0.4
W_PEOPLE = 0.4

# Tope del aporte de personas después de calibrar (4.1): compartir a alguien muy raro
# no tapa lo demás.
PEOPLE_CAP = 2.0

# Calibración (4.1): cada señal se divide por la mediana de la similitud con el
# CALIBRATION_RANK-ésimo vecino, sobre CALIBRATION_SAMPLE películas al azar.
CALIBRATION_RANK = 10
CALIBRATION_SAMPLE = 1000
CALIBRATION_SEED = 2026

# Vecinos precalculados por película (R15, 7.1), y bloque de filas al calcularlos.
NEIGHBORS = 100
NEIGHBORS_BLOCK = 1000

# Promedio bayesiano (R4, R5, 3.3).
M_OWN = 5  # m: votos propios para contradecir a IMDb
M_IMDB = 3000  # M: votos de IMDb para creerle a su promedio

# Punto medio del usuario (R10, 4.2).
K_USER = 5

# Ajuste final de la lista (R19, 4.3).
BETA = 0.2  # piso de calidad, sobre el WR estandarizado
LAMBDA = 0.8  # MMR
CANDIDATES = 200  # candidatas antes de MMR

# Recálculo del WR en segundo plano (R18, 7.2).
WR_REFRESH = 60.0
