"""The same question is not asked upstream twice; a failure is not remembered."""

from __future__ import annotations

import httpx
from app.cache import TTLCache
from conftest import LAST_PUBLISHED, ok, rates_payload

PARAMS = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}


def test_a_repeated_question_does_not_re_ask_the_upstream(make_client):
    with make_client(lambda request: ok(rates_payload(rate_date=LAST_PUBLISHED))) as client:
        first = client.get("/tools/convert", params=PARAMS)
        second = client.get("/tools/convert", params=PARAMS)

        assert client.upstream.call_count == 1

    assert first.json() == second.json()


def test_a_different_amount_reuses_the_cached_rate(make_client):
    with make_client(lambda request: ok(rates_payload(rate_date=LAST_PUBLISHED))) as client:
        client.get("/tools/convert", params=PARAMS)
        response = client.get("/tools/convert", params={**PARAMS, "amount": "1"})

        assert client.upstream.call_count == 1

    assert response.json()["result"] == 47.12


def test_a_different_date_is_a_different_question(make_client):
    with make_client(lambda request: ok(rates_payload(rate_date=LAST_PUBLISHED))) as client:
        client.get("/tools/convert", params=PARAMS)
        client.get("/tools/convert", params={**PARAMS, "date": "2026-08-27"})

        assert client.upstream.call_count == 2


def test_a_different_pair_is_a_different_question(make_client):
    def handler(request):
        target = request.url.params["symbols"]
        return ok(rates_payload(target=target, rate_date=LAST_PUBLISHED))

    with make_client(handler) as client:
        client.get("/tools/convert", params=PARAMS)
        client.get("/tools/convert", params={**PARAMS, "to": "USD"})

        assert client.upstream.call_count == 2


def test_a_failure_is_not_cached(make_client):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return ok(rates_payload(rate_date=LAST_PUBLISHED))

    with make_client(handler) as client:
        first = client.get("/tools/convert", params=PARAMS)
        second = client.get("/tools/convert", params=PARAMS)

    assert first.status_code == 502
    assert second.status_code == 200


def test_entries_expire():
    now = {"t": 0.0}
    cache: TTLCache[str] = TTLCache(clock=lambda: now["t"])
    cache.set("k", "v", ttl_seconds=10)

    now["t"] = 9.0
    assert cache.get("k") == "v"

    now["t"] = 10.0
    assert cache.get("k") is None


def test_the_cache_is_bounded():
    cache: TTLCache[int] = TTLCache(maxsize=2)
    cache.set("a", 1, ttl_seconds=60)
    cache.set("b", 2, ttl_seconds=60)
    cache.set("c", 3, ttl_seconds=60)

    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
