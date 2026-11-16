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
