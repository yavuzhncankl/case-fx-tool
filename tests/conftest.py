"""Test scaffolding: a fake upstream that lives inside the test process.

The suite never opens a socket. `httpx.MockTransport` answers every upstream
request from a Python function, so `./test.sh` passes with no network at all,
whatever `FX_UPSTREAM_BASE` points at.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import create_app
from app.upstream import FrankfurterClient

# A fixed "today" so the future-date and latest-rate tests do not drift.
# 2026-08-31 is a Monday; 2026-08-30 is the Sunday before it and 2026-08-28
# the Friday whose rates the ECB last published.
TODAY = date(2026, 8, 31)
LAST_PUBLISHED = date(2026, 8, 28)

UpstreamHandler = Callable[[httpx.Request], httpx.Response]


class FakeUpstream:
    """Records what the service asked, and answers however the test wants."""

    def __init__(self, handler: UpstreamHandler) -> None:
        self._handler = handler
        self.requests: list[httpx.Request] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def rates_payload(
    *,
    base: str = "EUR",
    target: str = "TRY",
    rate: float | str = 47.1234,
    rate_date: date = LAST_PUBLISHED,
    amount: float = 1.0,
) -> dict:
    """The shape the real upstream returns."""
    return {
        "amount": amount,
        "base": base,
        "date": rate_date.isoformat(),
        "rates": {target: rate},
    }


def ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


@pytest.fixture
def make_client(monkeypatch) -> Iterator[Callable[..., TestClient]]:
    """Build a TestClient wired to a fake upstream and a frozen 'today'."""
    created: list[TestClient] = []

    def factory(handler: UpstreamHandler, today: date = TODAY) -> TestClient:
        monkeypatch.setattr(main, "ecb_today", lambda: today)
        fake = FakeUpstream(handler)
        upstream = FrankfurterClient(
            base_url="http://upstream.test",
            transport=httpx.MockTransport(fake),
        )
        client = TestClient(create_app(upstream))
        client.upstream = fake  # type: ignore[attr-defined]
        created.append(client)
        return client

    yield factory

    for client in created:
        client.close()


@pytest.fixture
def client(make_client) -> TestClient:
    """The common case: the upstream answers with a normal EUR/TRY rate."""
    with make_client(lambda request: ok(rates_payload())) as started:
        yield started
