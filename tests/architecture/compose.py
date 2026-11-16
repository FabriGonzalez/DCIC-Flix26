"""Acceso a `docker compose` desde los tests, con subprocess (D16)."""

import json
import subprocess
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Ejecuta `docker compose <args>` en la raíz del repo."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
    )


@cache
def config() -> dict:
    """La configuración ya resuelta (variables, defaults), sin perfiles activos."""
    return json.loads(run("config", "--format", "json").stdout)


def services() -> dict[str, dict]:
    return config()["services"]


def rabbitmqctl(*args: str) -> list[dict]:
    """Ejecuta `rabbitmqctl <args>` dentro del contenedor y devuelve su salida JSON."""
    out = run("exec", "-T", "rabbitmq", "rabbitmqctl", "-q", "--formatter", "json", *args).stdout
    return json.loads(out)


def containers() -> dict[str, dict]:
    """Estado de los contenedores del proyecto, incluidos los terminados, por servicio."""
    out = run("ps", "--all", "--format", "json").stdout.strip()
    if not out:
        return {}
    # Según la versión, Compose devuelve una lista JSON o un objeto por línea.
    if out.startswith("["):
        rows = json.loads(out)
    else:
        rows = [json.loads(line) for line in out.splitlines()]
    return {row["Service"]: row for row in rows}


def exec_python(service: str, code: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta `python -c <code> <args>` dentro del contenedor del servicio."""
    return run("exec", "-T", service, "python", "-c", code, *args, check=False)
