"""Votos de prueba, por la cola real (tests del ingest-consumer) o por la API.

Usan un usuario nuevo en cada test y se borran al terminar: la base queda como estaba.
"""

import json
import uuid

import pytest

import compose
from dcicflix_common import topology

# Se publica desde el cleaning-agent, que tiene pika y la librería común: así se puede
# publicar también con el ingest-consumer detenido.
_CLIENT = "cleaning-agent"
_PUBLISH = """
import os, sys, pika
params = pika.ConnectionParameters(
    os.environ["RABBITMQ_HOST"],
    credentials=pika.PlainCredentials(os.environ["RABBITMQ_USER"], os.environ["RABBITMQ_PASSWORD"]),
)
with pika.BlockingConnection(params) as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_publish("", sys.argv[1], sys.argv[2].encode(), pika.BasicProperties(delivery_mode=2), mandatory=True)
"""


def mongo(script: str):
    result = compose.mongosh(f"print(JSON.stringify({script}))")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def queue() -> dict:
    """Mensajes listos, entregados sin responder y consumidores de `interactions`."""
    rows = compose.rabbitmqctl("list_queues", "name", "messages_ready", "messages_unacknowledged", "consumers")
    return next(row for row in rows if row["name"] == topology.INTERACTIONS_QUEUE)


def is_drained() -> bool:
    state = queue()
    return state["messages_ready"] == 0 and state["messages_unacknowledged"] == 0


class Voter:
    """Un usuario de prueba que vota una película activa."""

    NAME = "Votante de prueba"

    def __init__(self):
        movie = mongo("db.movies.findOne({deleted: false}, {num_mflix_comments: 1})")
        if movie is None:
            pytest.skip("no hay películas activas: la limpieza todavía no terminó")
        self.user_id = f"test_{uuid.uuid4().hex[:12]}"
        self.movie_id = movie["_id"]
        self.initial_count = movie["num_mflix_comments"]

    def message(self, rating: int, second: int = 0) -> dict:
        return {
            "user_id": self.user_id,
            "movie_id": self.movie_id,
            "rating": rating,
            "comment": "Muy buena",
            "votedAt": f"2026-11-23T12:00:{second:02d}.000Z",
        }

    def publish(self, rating: int, second: int = 0) -> None:
        body = json.dumps(self.message(rating, second))
        result = compose.exec_python(_CLIENT, _PUBLISH, topology.INTERACTIONS_QUEUE, body)
        assert result.returncode == 0, result.stderr

    def register(self) -> None:
        """Agrega el usuario a `users`: sin eso, la API no acepta sus votos."""
        mongo(f'db.users.insertOne({{_id: "{self.user_id}", name: "{self.NAME}", email: "", preloaded: false}})')

    def post(self, rating: int) -> int:
        """Vota por la API, a través del frontend. Devuelve el código HTTP."""
        body = {"userId": self.user_id, "rating": rating, "comment": "Muy buena"}
        return compose.post_to_frontend(f"/api/movies/{self.movie_id}/reviews", body)[0]

    def saved(self) -> list[int]:
        """Las estrellas de los votos guardados: con uno solo, una lista de un elemento."""
        return mongo(f'db.reviews.find({{user_id: "{self.user_id}"}}).toArray().map(r => r.rating)')

    def added_to_count(self) -> int:
        movie = mongo(f'db.movies.findOne({{_id: ObjectId("{self.movie_id}")}}, {{num_mflix_comments: 1}})')
        return movie["num_mflix_comments"] - self.initial_count

    def clean(self) -> None:
        # Sin assert: si Mongo no volvió, la falla ya está informada en el test.
        compose.mongosh(f"""
            db.users.deleteOne({{_id: "{self.user_id}"}});
            db.reviews.deleteMany({{user_id: "{self.user_id}"}});
            db.movies.updateOne(
                {{_id: ObjectId("{self.movie_id}")}}, {{$set: {{num_mflix_comments: {self.initial_count}}}}});
        """)
