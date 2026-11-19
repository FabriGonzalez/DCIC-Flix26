"""Topología de RabbitMQ (D11). SOLO DATOS.

Este es el único lugar con nombres de exchanges y colas (D9). `topology-init` la
declara, los servicios la verifican y los tests de arquitectura la comparan
contra el broker.

    interactions (cola) --dead-letter--> interactions.dlx (fanout) --> interactions.errors (cola)
    data.cleaned (fanout) --> recommender.data-cleaned (cola)
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Exchange:
    name: str
    type: str
    durable: bool = True


@dataclass(frozen=True)
class Queue:
    name: str
    durable: bool = True
    arguments: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Binding:
    exchange: str
    queue: str
    routing_key: str = ""


# Nombres que usan los servicios.
INTERACTIONS_QUEUE = "interactions"
INTERACTIONS_DLX = "interactions.dlx"
INTERACTIONS_ERRORS_QUEUE = "interactions.errors"
DATA_CLEANED_EXCHANGE = "data.cleaned"
RECOMMENDER_DATA_CLEANED_QUEUE = "recommender.data-cleaned"

EXCHANGES = (
    Exchange(INTERACTIONS_DLX, "fanout"),
    Exchange(DATA_CLEANED_EXCHANGE, "fanout"),
)

QUEUES = (
    # El backend publica en el exchange por defecto con routing key "interactions".
    Queue(INTERACTIONS_QUEUE, arguments={"x-dead-letter-exchange": INTERACTIONS_DLX}),
    Queue(INTERACTIONS_ERRORS_QUEUE),
    Queue(RECOMMENDER_DATA_CLEANED_QUEUE),
)

BINDINGS = (
    Binding(INTERACTIONS_DLX, INTERACTIONS_ERRORS_QUEUE),
    Binding(DATA_CLEANED_EXCHANGE, RECOMMENDER_DATA_CLEANED_QUEUE),
)
