"""Errores comunes a las variantes sync/ y aio/ del helper."""


class TopologyError(RuntimeError):
    """El broker no tiene la topología de topology.py. Es irrecuperable (D14)."""


class BackgroundTaskError(RuntimeError):
    """Falló el trabajo de un servicio en su hilo aparte. Es irrecuperable (D14): el
    proceso termina y Docker lo reinicia, en lugar de quedar vivo sin hacer su trabajo."""
