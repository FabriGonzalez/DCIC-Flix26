"""Acceso a `docker compose` desde los tests, con subprocess (D16)."""

import json
import subprocess
import urllib.error
import urllib.request
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str], check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
    )


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Ejecuta `docker compose <args>` en la raíz del repo."""
    return _run(["docker", "compose", *args], check)


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


def inspect() -> dict[str, dict]:
    """`docker inspect` de los contenedores del proyecto, por servicio.

    Trae lo que `compose ps` no muestra, como `RestartCount` y `State.StartedAt`.
    """
    ids = run("ps", "--all", "--quiet").stdout.split()
    if not ids:
        return {}
    found = json.loads(_run(["docker", "inspect", *ids], check=True).stdout)
    return {c["Config"]["Labels"]["com.docker.compose.service"]: c for c in found}


def mongosh(script: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta `script` con mongosh dentro de `mongodb`, en la base de los servicios.

    Usa las credenciales ya resueltas del compose: respeta el .env.
    """
    env = services()["mongodb"]["environment"]
    database = services()["backend"]["environment"]["MONGO_DB"]
    return run(
        "exec", "-T", "mongodb", "mongosh", "--quiet",
        "-u", env["MONGO_INITDB_ROOT_USERNAME"],
        "-p", env["MONGO_INITDB_ROOT_PASSWORD"],
        "--authenticationDatabase", "admin",
        database, "--eval", script,
        check=False,
    )  # fmt: skip

def exec_python(service: str, code: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta `python -c <code> <args>` dentro del contenedor del servicio."""
    return run("exec", "-T", service, "python", "-c", code, *args, check=False)


def exec_sh(service: str, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta `sh -c <script> sh <args>` dentro del contenedor (imágenes sin Python)."""
    return run("exec", "-T", service, "sh", "-c", script, "sh", *args, check=False)


def published_port(service: str, target: int) -> int:
    """Puerto del host publicado para el puerto `target` del servicio (respeta el .env)."""
    for port in services()[service].get("ports", []):
        if port.get("target") == target and port.get("published"):
            return int(port["published"])
    raise LookupError(f"{service} no publica el puerto {target}")


def get_from_frontend(path: str) -> tuple[int, str, str]:
    """GET desde el host al puerto publicado del frontend: (código, content-type, cuerpo)."""
    port = published_port("frontend", 80)
    try:
        response = urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    return response.status, response.headers.get("content-type", ""), response.read().decode()
