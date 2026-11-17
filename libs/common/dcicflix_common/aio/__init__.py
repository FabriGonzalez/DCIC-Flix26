"""Variante asyncio del helper (extra [async]): backend y recommender.

Todo corre en un event loop, en un solo hilo. aio-pika atiende la conexión con Rabbit
(heartbeat AMQP incluido) mientras el loop esté libre. Regla: nunca bloquear el loop
con I/O sincrónica o cálculo pesado; eso va a un hilo o proceso (run_in_executor).
"""
