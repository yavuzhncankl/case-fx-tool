"""The conversion itself.

The one rule the whole file exists to keep: the response may never present a
rate as belonging to a date it does not belong to. `rate_date` is whatever the
upstream said, `asked_date` is whatever the caller asked, and when they differ
the response says so in a sentence the model can read to the customer.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .cache import TTL_HISTORIC_SECONDS, TTL_LATEST_SECONDS, TTLCache
from .errors import FxError
from .upstream import FrankfurterClient, Quote

SOURCE = "ECB via frankfurter.dev"
IDENTITY_SOURCE = "identity (no upstream rate involved)"
CENTS = Decimal("0.01")


def _as_number(value: Decimal) -> float:
    return float(value)


def _identity_response(amount: Decimal, code: str, asked_date: date) -> dict:
    return {
        "amount": _as_number(amount),
        "from": code,
        "to": code,
        "rate": 1.0,
        "result": _as_number(amount.quantize(CENTS, rounding=ROUND_HALF_UP)),
        "rate_date": asked_date.isoformat(),
        "asked_date": asked_date.isoformat(),
        "source": IDENTITY_SOURCE,
    }


async def convert(
    client: FrankfurterClient,
    cache: TTLCache[Quote],
    *,
    amount: Decimal,
    base: str,
    target: str,
    asked: date | None,
    today: date,
) -> dict:
    asked_date = asked if asked is not None else today

    if base == target:
        # No upstream rate is involved, so we do not claim one. A conversion
        # into the same currency is the amount itself, on any date.
        return _identity_response(amount, base, asked_date)

    cache_key = (base, target, asked.isoformat() if asked is not None else "latest")
    quote = cache.get(cache_key)
    if quote is None:
        quote = await client.fetch(base, target, asked)
        _guard(quote, asked_date, today)
        ttl = TTL_HISTORIC_SECONDS if asked is not None and asked < today else TTL_LATEST_SECONDS
        cache.set(cache_key, quote, ttl)

    result = (amount * quote.rate).quantize(CENTS, rounding=ROUND_HALF_UP)

    response = {
        "amount": _as_number(amount),
        "from": base,
        "to": target,
        "rate": _as_number(quote.rate),
        "result": _as_number(result),
        "rate_date": quote.rate_date.isoformat(),
        "asked_date": asked_date.isoformat(),
        "source": SOURCE,
    }

    if quote.rate_date != asked_date:
        # Weekend, public holiday, or a request made before the day's rates are
        # published. We answer with the last published rate — and we say which
        # day it is from, because the customer is going to be told a number.
        if asked is None:
            response["note"] = (
                f"The most recent rate the ECB has published is from "
                f"{quote.rate_date.isoformat()}."
            )
        else:
            response["note"] = (
                f"The ECB published no rate for {asked_date.isoformat()}. "
                f"This result uses the rate published on {quote.rate_date.isoformat()}."
            )

    return response


def _guard(quote: Quote, asked_date: date, today: date) -> None:
    """Refuse an upstream answer that cannot be true.

    A rate dated after the day it was asked for — or after today — is either an
    upstream bug or a fake upstream. Either way, answering with it would put a
    number in front of a customer under the wrong date.
    """
    if quote.rate_date > asked_date or quote.rate_date > today:
        raise FxError(
            "upstream_invalid_response",
            "The exchange-rate source returned a rate dated after the day that was asked for, "
            "so it cannot be used.",
            status_code=502,
        )
