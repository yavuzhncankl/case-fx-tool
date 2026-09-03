"""Bad input never reaches the upstream, and never produces a number."""

from __future__ import annotations

import pytest
from conftest import ok, rates_payload


def never_called(request):  # pragma: no cover - asserted through call_count
    raise AssertionError("the upstream must not be asked when the input is invalid")


@pytest.mark.parametrize(
    "params, code",
    [
        ({"from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "", "from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "0", "from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "-250", "from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "abc", "from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "NaN", "from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "Infinity", "from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "1e13", "from": "EUR", "to": "TRY"}, "invalid_amount"),
        ({"amount": "250", "to": "TRY"}, "invalid_currency"),
        ({"amount": "250", "from": "EUR"}, "invalid_currency"),
        ({"amount": "250", "from": "EURO", "to": "TRY"}, "invalid_currency"),
        ({"amount": "250", "from": "E1R", "to": "TRY"}, "invalid_currency"),
        ({"amount": "250", "from": "EUR", "to": "TRY", "date": "28-08-2026"}, "invalid_date"),
        ({"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-02-30"}, "invalid_date"),
        ({"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-09-01"}, "date_in_future"),
        ({"amount": "250", "from": "EUR", "to": "TRY", "date": "1998-12-31"}, "date_out_of_range"),
    ],
)
def test_bad_input_is_rejected_without_asking_the_upstream(make_client, params, code):
    with make_client(never_called) as client:
        response = client.get("/tools/convert", params=params)

        assert response.status_code == 400
        assert response.json()["error"] == code
        assert response.json()["message"]
        assert client.upstream.call_count == 0


def test_error_bodies_carry_only_a_code_and_a_message(make_client):
    with make_client(never_called) as client:
        body = client.get("/tools/convert", params={"from": "EUR", "to": "TRY"}).json()

    assert set(body) == {"error", "message"}
    assert body["message"].endswith(".")


def test_a_date_of_today_is_not_in_the_future(make_client):
    with make_client(lambda request: ok(rates_payload())) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "1", "from": "EUR", "to": "TRY", "date": "2026-08-31"},
        )

    assert response.status_code == 200


def test_the_first_day_of_the_series_is_accepted(make_client):
    from datetime import date

    with make_client(lambda request: ok(rates_payload(rate_date=date(1999, 1, 4)))) as client:
        response = client.get(
            "/tools/convert",
            params={"amount": "1", "from": "EUR", "to": "TRY", "date": "1999-01-04"},
        )

    assert response.status_code == 200
