"""Errores comunes a las variantes sync/ y aio/ del helper."""


class TopologyError(RuntimeError):
    """El broker no tiene la topología de topology.py. Es irrecuperable (D14)."""
