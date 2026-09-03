"""When the upstream misbehaves, the caller gets an error — never a number."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from conftest import ok, rates_payload

GOOD = {"amount": "250", "from": "EUR", "to": "TRY"}


def _raise(exc_type):
    def handler(request):
        raise exc_type("simulated", request=request)

    return handler


@pytest.mark.parametrize(
    "handler, status, code",
    [
        (_raise(httpx.ReadTimeout), 504, "upstream_timeout"),
        (_raise(httpx.ConnectTimeout), 504, "upstream_timeout"),
        (_raise(httpx.ConnectError), 502, "upstream_unavailable"),
        (lambda request: httpx.Response(500, text="boom"), 502, "upstream_unavailable"),
        (lambda request: httpx.Response(503, text="down"), 502, "upstream_unavailable"),
        (lambda request: httpx.Response(429, text="slow down"), 503, "upstream_unavailable"),
        (
            lambda request: httpx.Response(200, text="<html>maintenance</html>"),
            502,
            "upstream_invalid_response",
        ),
        (lambda request: httpx.Response(200, json=[1, 2, 3]), 502, "upstream_invalid_response"),
        (
            lambda request: httpx.Response(200, json={"date": "2026-08-28"}),
            502,
            "upstream_invalid_response",
        ),
        (
            lambda request: httpx.Response(200, json={"rates": {"TRY": 47.1}}),
            502,
            "upstream_invalid_response",
        ),
        (
            lambda request: httpx.Response(
                200, json={"date": "not-a-date", "rates": {"TRY": 47.1}}
            ),
            502,
            "upstream_invalid_response",
        ),
        (
            lambda request: httpx.Response(
                200, json={"date": "2026-08-28", "rates": {"TRY": "not-a-number"}}
            ),
            502,
            "upstream_invalid_response",
        ),
        (
            lambda request: httpx.Response(200, json={"date": "2026-08-28", "rates": {"TRY": 0}}),
            502,
            "upstream_invalid_response",
        ),
        (
            lambda request: httpx.Response(200, json={"date": "2026-08-28", "rates": {"TRY": -3}}),
            502,
            "upstream_invalid_response",
        ),
    ],
)
def test_upstream_trouble_never_becomes_a_rate(make_client, handler, status, code):
    with make_client(handler) as client:
        response = client.get("/tools/convert", params=GOOD)

    body = response.json()
    assert response.status_code == status
    assert body["error"] == code
    assert set(body) == {"error", "message"}
    assert "rate" not in body and "result" not in body


def test_unknown_currency_reported_by_a_missing_symbol(make_client):
    payload = {"amount": 1.0, "base": "EUR", "date": "2026-08-28", "rates": {}}
    with make_client(lambda request: httpx.Response(200, json=payload)) as client:
        response = client.get("/tools/convert", params={"amount": "1", "from": "EUR", "to": "XYZ"})

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_currency"


def test_unknown_currency_reported_by_a_404_on_the_latest_rates(make_client):
    with make_client(lambda request: httpx.Response(404, json={"message": "not found"})) as client:
        response = client.get("/tools/convert", params={"amount": "1", "from": "EUR", "to": "XYZ"})

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_currency"


def test_a_404_on_a_dated_request_is_reported_as_a_missing_rate_for_that_date(make_client):
    with make_client(lambda request: httpx.Response(404, json={"message": "not found"})) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "1", "from": "EUR", "to": "TRY", "date": "2026-08-28"},
        )

    body = response.json()
    assert response.status_code == 404
    assert body["error"] == "no_rate_for_date"
    assert "2026-08-28" in body["message"]


def test_a_rate_dated_after_the_day_asked_for_is_refused(make_client):
    """A rate from a later day is not the rate that was asked for. Answering
    with it would tell a customer a number under the wrong date."""
    with make_client(lambda request: ok(rates_payload(rate_date=date(2026, 8, 31)))) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "1", "from": "EUR", "to": "TRY", "date": "2026-08-28"},
        )

    assert response.status_code == 502
    assert response.json()["error"] == "upstream_invalid_response"
