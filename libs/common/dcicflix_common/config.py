"""Configuración de los servicios, leída de variables de entorno.

Cada servicio pide solo las piezas que usa. Si falta una variable obligatoria,
el servicio falla al arrancar con un mensaje que las nombra a todas, en lugar de
fallar más tarde con un error de conexión confuso.
"""

import os
from dataclasses import dataclass
from urllib.parse import quote_plus


class ConfigError(RuntimeError):
    """Faltan variables de entorno obligatorias."""


def _require(*names: str) -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError("faltan variables de entorno: " + ", ".join(missing))
    return values


@dataclass(frozen=True)
class RabbitSettings:
    host: str
    user: str
    password: str
    port: int = 5672

    @classmethod
    def from_env(cls) -> "RabbitSettings":
        env = _require("RABBITMQ_HOST", "RABBITMQ_USER", "RABBITMQ_PASSWORD")
        return cls(env["RABBITMQ_HOST"], env["RABBITMQ_USER"], env["RABBITMQ_PASSWORD"])

    def __repr__(self) -> str:  # sin la contraseña, por si termina en un log
        return f"RabbitSettings(host={self.host!r}, port={self.port}, user={self.user!r})"


@dataclass(frozen=True)
class MongoSettings:
    host: str
    user: str
    password: str
    db: str
    port: int = 27017

    @classmethod
    def from_env(cls) -> "MongoSettings":
        env = _require("MONGO_HOST", "MONGO_USER", "MONGO_PASSWORD", "MONGO_DB")
        return cls(env["MONGO_HOST"], env["MONGO_USER"], env["MONGO_PASSWORD"], env["MONGO_DB"])

    @property
    def uri(self) -> str:
        # authSource=admin: el usuario root se crea en la base admin, no en MONGO_DB.
        # quote_plus: un "@" o un "/" en la contraseña no rompe la URI.
        return (
            f"mongodb://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.db}?authSource=admin"
        )

    def __repr__(self) -> str:
        return f"MongoSettings(host={self.host!r}, port={self.port}, user={self.user!r}, db={self.db!r})"


def log_level() -> str:
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def recommender_url() -> str:
    """URL base del recommender, para el backend (por ejemplo http://recommender:8000)."""
    return _require("RECOMMENDER_URL")["RECOMMENDER_URL"].rstrip("/")


def llm_api_key() -> str | None:
    """Opcional (D15): sin key, las funciones con LLM quedan deshabilitadas."""
    return os.environ.get("LLM_API_KEY") or None
