import asyncio

import httpx
import pytest

from app import status
from dcicflix_common import cleaning


@pytest.mark.parametrize(
    ("mark", "recommender_ready", "expected"),
    [
        (None, False, status.CLEANING),  # sin documento: la limpieza no empezó
        (None, True, status.CLEANING),
        (cleaning.PENDING, True, status.CLEANING),
        (cleaning.RUNNING, False, status.CLEANING),
        (cleaning.RUNNING, True, status.CLEANING),  # recommender listo con datos viejos: manda la marca
        (cleaning.DONE, False, status.INDEXING),
        (cleaning.DONE, True, status.READY),
        ("otra cosa", True, status.CLEANING),  # una marca desconocida no es "done"
    ],
)
def test_combine(mark, recommender_ready, expected):
    assert status.combine(mark, recommender_ready) == expected


def probe_answering(handler) -> status.RecommenderProbe:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return status.RecommenderProbe(http, "http://recommender:8000")


def run_check(probe: status.RecommenderProbe) -> None:
    asyncio.run(probe.check())


def test_probe_ready():
    probe = probe_answering(lambda request: httpx.Response(200, json={"status": "ok", "ready": True}))
    run_check(probe)
    assert probe.ready


def test_probe_healthy_but_not_ready():
    # El caso que motivó RecommenderProbe: 200 mientras embebe o indexa.
    probe = probe_answering(lambda request: httpx.Response(200, json={"status": "ok", "ready": False}))
    run_check(probe)
    assert not probe.ready


def test_probe_without_ready_field_is_not_ready():
    probe = probe_answering(lambda request: httpx.Response(200, json={"status": "ok"}))
    run_check(probe)
    assert not probe.ready


def test_probe_unhealthy_fails_the_check_and_is_not_ready():
    probe = probe_answering(lambda request: httpx.Response(503, json={"status": "error", "ready": True}))
    with pytest.raises(httpx.HTTPStatusError):
        run_check(probe)
    assert not probe.ready


def test_probe_goes_back_to_not_ready_when_recommender_falls():
    answers = iter([httpx.Response(200, json={"ready": True})])

    def handler(request):
        try:
            return next(answers)
        except StopIteration:
            raise httpx.ConnectError("recommender caído") from None

    probe = probe_answering(handler)
    run_check(probe)
    assert probe.ready
    with pytest.raises(httpx.ConnectError):
        run_check(probe)
    assert not probe.ready


def test_probe_keeps_the_last_answer_while_it_asks_again():
    # Si no, cada 10 s habría un instante en "indexing", y un voto en ese instante daría 409.
    seen = []

    def handler(request):
        seen.append(probe.ready)
        return httpx.Response(200, json={"ready": True})

    probe = probe_answering(handler)
    run_check(probe)
    run_check(probe)
    assert seen == [False, True]
    assert probe.ready


def test_probe_cancelled_by_the_monitor_is_not_ready():
    # El monitor corta un chequeo que tarda demasiado.
    async def hung(request):
        await asyncio.sleep(60)

    async def go():
        probe = probe_answering(hung)
        probe.ready = True
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(probe.check(), 0.05)
        return probe

    assert not asyncio.run(go()).ready
