import pytest

from dcicflix_common import config
from dcicflix_common.config import ConfigError, MongoSettings, RabbitSettings


def test_falta_de_variables_las_nombra_a_todas(monkeypatch):
    monkeypatch.setenv("RABBITMQ_HOST", "rabbitmq")
    monkeypatch.delenv("RABBITMQ_USER", raising=False)
    monkeypatch.setenv("RABBITMQ_PASSWORD", "")
    with pytest.raises(ConfigError, match="RABBITMQ_USER, RABBITMQ_PASSWORD"):
        RabbitSettings.from_env()


def test_uri_de_mongo_escapa_credenciales_y_autentica_en_admin():
    settings = MongoSettings(host="mongodb", user="ana", password="p@ss/:word", db="peliculas-proyectos")
    assert settings.uri == "mongodb://ana:p%40ss%2F%3Aword@mongodb:27017/peliculas-proyectos?authSource=admin"


@pytest.mark.parametrize(
    "settings",
    [RabbitSettings("rabbitmq", "ana", "secreta"), MongoSettings("mongodb", "ana", "secreta", "db")],
    ids=["rabbit", "mongo"],
)
def test_repr_no_muestra_la_contrasena(settings):
    assert "secreta" not in repr(settings)


def test_api_key_del_llm_es_opcional(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    assert config.llm_api_key() is None
