"""The happy paths, and the one that is not quite happy: a date with no rate."""

from __future__ import annotations

from datetime import date

from conftest import LAST_PUBLISHED, TODAY, ok, rates_payload


def test_converts_and_reports_the_date_the_rate_belongs_to(make_client):
    with make_client(lambda request: ok(rates_payload(rate_date=date(2026, 8, 28)))) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "amount": 250.0,
        "from": "EUR",
        "to": "TRY",
        "rate": 47.1234,
        "result": 11780.85,
        "rate_date": "2026-08-28",
        "asked_date": "2026-08-28",
        "source": "ECB via frankfurter.dev",
    }


def test_asks_the_upstream_for_the_date_the_caller_asked_for(make_client):
    with make_client(lambda request: ok(rates_payload(rate_date=date(2026, 8, 28)))) as client:
        client.get(
            "/tools/convert",
            params={"amount": "1", "from": "EUR", "to": "TRY", "date": "2026-08-28"},
        )
        request = client.upstream.requests[0]

    assert request.url.path == "/v1/2026-08-28"
    assert request.url.params["base"] == "EUR"
    assert request.url.params["symbols"] == "TRY"


def test_weekend_answers_with_the_last_published_rate_and_says_so(make_client):
    """A Sunday has no ECB rate. We answer, but the date we answer with is
    Friday's — and the response says which day the number is from."""
    with make_client(lambda request: ok(rates_payload(rate_date=LAST_PUBLISHED))) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "100", "from": "EUR", "to": "TRY", "date": "2026-08-30"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["asked_date"] == "2026-08-30"
    assert body["rate_date"] == "2026-08-28"
    assert "2026-08-28" in body["note"]
    assert "no rate for 2026-08-30" in body["note"]


def test_no_date_means_latest_and_asked_date_is_today(make_client):
    with make_client(lambda request: ok(rates_payload(rate_date=TODAY))) as client:
        response = client.get("/tools/convert", params={"amount": "10", "from": "EUR", "to": "TRY"})
        request = client.upstream.requests[0]

    body = response.json()
    assert request.url.path == "/v1/latest"
    assert body["asked_date"] == TODAY.isoformat()
    assert body["rate_date"] == TODAY.isoformat()
    assert "note" not in body


def test_latest_rate_older_than_today_is_flagged(make_client):
    """Before ~16:00 CET the newest published rate is yesterday's. The caller
    still gets a number, and still gets told which day it is from."""
    with make_client(lambda request: ok(rates_payload(rate_date=LAST_PUBLISHED))) as client:
        response = client.get("/tools/convert", params={"amount": "10", "from": "EUR", "to": "TRY"})

    body = response.json()
    assert body["rate_date"] == "2026-08-28"
    assert body["asked_date"] == TODAY.isoformat()
    assert body["note"] == "The most recent rate the ECB has published is from 2026-08-28."


def test_same_currency_is_answered_without_an_upstream_rate(make_client):
    def fail(request):  # pragma: no cover - proving it is never called
        raise AssertionError("the upstream must not be asked for an identity conversion")

    with make_client(fail) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "250.5", "from": "EUR", "to": "eur"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["rate"] == 1.0
    assert body["result"] == 250.5
    assert body["source"] == "identity (no upstream rate involved)"
    assert client.upstream.call_count == 0


def test_currency_codes_are_case_insensitive(make_client):
    with make_client(lambda request: ok(rates_payload())) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "1", "from": "eur", "to": "try"},
        )
        request = client.upstream.requests[0]

    body = response.json()
    assert body["from"] == "EUR"
    assert body["to"] == "TRY"
    assert request.url.params["base"] == "EUR"


def test_rate_is_returned_at_full_precision(make_client):
    """Rounding the rate itself before multiplying loses money on large
    amounts; only the result is rounded."""
    with make_client(lambda request: ok(rates_payload(rate="47.123456"))) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "1000000", "from": "EUR", "to": "TRY"},
        )

    body = response.json()
    assert body["rate"] == 47.123456
    assert body["result"] == 47123456.0


def test_result_is_rounded_half_up_to_two_decimals(make_client):
    with make_client(lambda request: ok(rates_payload(rate="1.005"))) as client:
        response = client.get("/tools/convert", params={"amount": "1", "from": "EUR", "to": "TRY"})

    assert response.json()["result"] == 1.01


def test_many_decimal_places_in_amount_are_accepted(make_client):
    with make_client(lambda request: ok(rates_payload(rate="2"))) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "1.0000000001", "from": "EUR", "to": "TRY"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["result"] == 2.0


def test_health(client):
    assert client.get("/health").json() == {"ok": True}
