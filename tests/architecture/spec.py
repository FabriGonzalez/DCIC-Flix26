"""La arquitectura esperada, como datos.

Los tests comparan el sistema real contra estas tablas. Un cambio de arquitectura
se hace primero acá, y queda a la vista en el diff.
Diseño: docs/esqueleto-contenedores.md
"""

# Redes del README. Ninguna otra, y en particular no la `default` de Compose.
NETWORKS = {"public-net", "internal-net", "egress-net"}

# Redes sin salida a internet.
INTERNAL_NETWORKS = {"internal-net"}

# Únicos servicios con puerto publicado en el host (en modo normal, sin perfiles).
PUBLISHED_PORTS_ALLOWED = {"frontend"}

# Servicios que corren una vez y terminan. Sin healthcheck y sin reinicio;
# lo esperado es que queden en Exited (0).
ONE_SHOT_SERVICES = {"topology-init"}

# Política de reinicio de los servicios de larga vida.
LONG_LIVED_RESTART = "unless-stopped"

# Matriz de alcance y aislamiento: la tabla de comunicación del README, como datos.
# Por cada servicio propio de larga vida:
#   resolves:     nombres que tiene que resolver (sus dependencias)
#   not_resolves: nombres que no tiene que resolver (aislamiento entre redes)
#   internet:     si sale a internet
# Un nombre de un servicio que todavía no existe en el compose se saltea con aviso.
REACHABILITY = {
    "backend": {
        "resolves": {"mongodb", "rabbitmq", "recommender"},
        "not_resolves": set(),
        "internet": True,  # public-net: API del LLM (traducción y chat)
    },
    "recommender": {
        "resolves": {"mongodb", "rabbitmq"},
        "not_resolves": {"frontend"},
        "internet": False,
    },
    "ingest-consumer": {
        "resolves": {"mongodb", "rabbitmq"},
        "not_resolves": {"frontend"},
        "internet": False,
    },
    "cleaning-agent": {
        "resolves": {"mongodb", "rabbitmq"},
        "not_resolves": {"frontend"},
        "internet": True,  # egress-net: API del LLM
    },
}

# Servicios con /health HTTP en el 8000, y sus dependencias informativas (D12).
HTTP_HEALTH_INFO = {
    "backend": {"recommender"},
    "recommender": set(),
}

# Destinos para probar la salida a internet: por IP (ruta) y por nombre (DNS + ruta).
# Con una red solo `internal`, Docker ni siquiera resuelve nombres externos: probar
# solo por nombre no distinguiría "sin DNS" de "sin ruta".
INTERNET_PROBES = (("1.1.1.1", 443), ("one.one.one.one", 443))
