# Mediciones del recomendador

Scripts que respaldan los números de [docs/recomendador.md](../../docs/recomendador.md). Leen el dataset crudo (`dataset/*.json.gz`), no MongoDB, así que no hace falta levantar los contenedores.

| Script | Sección | Qué mide | Necesita embeddings |
| :-- | :-- | :-- | :-- |
| `embeber.py` | 4.4 | Descarga del modelo y embedding de los 19.842 plots; deja `plots.npy` | — |
| `senal_plot.py` | 4.1 | Si las vecinas por plot comparten género más seguido que al azar | Sí |
| `m_y_M.py` | 3.4 | RMSE de `WR` para la grilla de `m` y `M` | No |
| `votos_sin_gustos.py` | 6.1 | Prueba de dejar una afuera, con votos tal cual y corregidos por calidad | Sí |
| `vecinos_precalculados.py` | 7.1 | Tiempo por petición: contra todo el catálogo vs. vecinos precalculados | Sí |
| `pesos.py` | 4.1, 4.3, 6.3 | Calibración, pesos, `β` y `λ` con la prueba de conjuntos escondidos | Sí |

En una PC con Windows y 4 CPUs, `embeber.py` tarda ≈ 6 min y `pesos.py` ≈ 1,5 min.

## Uso

Desde la raíz del repo, en un entorno virtual aparte:

```sh
python -m venv .venv-reco
.venv-reco/Scripts/pip install -r analysis/recomendador/requirements.txt    # Linux/macOS: .venv-reco/bin/pip

# Una vez: embeber los plots (deja analysis/recomendador/cache/plots.npy)
.venv-reco/Scripts/python -I -X utf8 analysis/recomendador/embeber.py dataset/movies.json.gz analysis/recomendador/cache

# Después, cualquiera de los demás
.venv-reco/Scripts/python -I -X utf8 analysis/recomendador/pesos.py dataset/movies.json.gz dataset/reviews.json.gz analysis/recomendador/cache/plots.npy
```

- `-X utf8` hace falta en Windows, porque los scripts imprimen `β`, `λ` y `≈`.
- La carpeta `cache/` (modelo y vectores, ≈ 300 MB) no se sube al repo.

## Limitaciones

- **Dataset crudo:** las copias duplicadas se aproximan quedándose con una por `imdb.id`. Con la base limpia hay que adaptar la lectura y volver a correr `m_y_M.py` y `pesos.py` (pendiente 7 del documento).
- **Escalas de 4.1:** la tabla de media, desvío y percentil 99 de cada señal se midió sin guardar un script. La calibración que se usa la calcula `pesos.py`.
