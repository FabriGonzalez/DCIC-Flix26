"""Forma común del estado de salud de los servicios (D12).

    {
      "service": "backend",
      "status": "ok",
      "dependencies": {"mongodb": "ok", "rabbitmq": "ok"},
      "info":         {"recommender": "ok"}
    }

`dependencies` son las críticas: si alguna no está en "ok", el servicio no está sano.
`info` son informativas: se muestran, pero no cambian `status`.
"""

OK = "ok"
ERROR = "error"


def report(service: str, dependencies: dict[str, str], info: dict[str, str] | None = None) -> dict:
    status = OK if all(value == OK for value in dependencies.values()) else ERROR
    return {
        "service": service,
        "status": status,
        "dependencies": dict(dependencies),
        "info": dict(info or {}),
    }
