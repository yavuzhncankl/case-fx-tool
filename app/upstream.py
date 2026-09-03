"""The only place that talks to the upstream rate feed.

Two rules live here:

1. The host comes from configuration, never from a literal in the code.
2. Nothing leaves this module unless it is a real number with a real date
   attached. Anything else — a timeout, a 500, an HTML error page, a payload
   missing the fields we need — becomes an `FxError`, never a rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from .errors import FxError


@dataclass(frozen=True)
class Quote:
    """A rate together with the date the upstream says it belongs to."""

    rate: Decimal
    rate_date: date


class FrankfurterClient:
    """A thin client for the Frankfurter/ECB feed.

    `transport` exists so the tests can serve a fake upstream in-process: the
    suite never opens a socket.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(2.0, timeout_seconds),
        )
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _url(self, on: date | None) -> str:
        path = on.isoformat() if on is not None else "latest"
        return f"{self.base_url}/v1/{path}"

    async def fetch(self, base: str, target: str, on: date | None) -> Quote:
        url = self._url(on)
        params = {"base": base, "symbols": target}
        try:
            response = await self._client.get(url, params=params)
        except httpx.TimeoutException:
            raise FxError(
                "upstream_timeout",
                "The exchange-rate source did not answer in time, so no rate is available right now.",
                status_code=504,
            ) from None
        except httpx.RequestError:
            raise FxError(
                "upstream_unavailable",
                "The exchange-rate source could not be reached, so no rate is available right now.",
                status_code=502,
            ) from None

        if response.status_code in (400, 404, 422):
            # A bare 404 does not say whether the pair is unknown or the date is
            # uncovered, so the answer depends on what was asked and the message
            # names both possibilities rather than guessing one.
            if on is not None:
                raise FxError(
                    "no_rate_for_date",
                    f"The exchange-rate source has no {base} to {target} rate for "
                    f"{on.isoformat()}: either that pair is not published or that date is "
                    f"not covered.",
                    status_code=404,
                )
            raise FxError(
                "unsupported_currency",
                f"The exchange-rate source does not publish a {base} to {target} rate.",
            )
        if response.status_code == 429:
            raise FxError(
                "upstream_unavailable",
                "The exchange-rate source is rate-limiting us, so no rate is available right now.",
                status_code=503,
            )
        if response.status_code >= 400:
            raise FxError(
                "upstream_unavailable",
                "The exchange-rate source returned an error, so no rate is available right now.",
                status_code=502,
            )

        try:
            payload = response.json()
        except ValueError:
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned something that is not a rate.",
                status_code=502,
            ) from None

        return self._to_quote(payload, base, target)

    @staticmethod
    def _to_quote(payload: object, base: str, target: str) -> Quote:
        if not isinstance(payload, dict):
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned something that is not a rate.",
                status_code=502,
            )

        rates = payload.get("rates")
        if not isinstance(rates, dict):
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned a response with no rates in it.",
                status_code=502,
            )

        if target not in rates:
            # The upstream answered, it just has nothing for this pair. That is
            # a bad request from the caller, not an outage.
            raise FxError(
                "unsupported_currency",
                f"The exchange-rate source does not publish a {base} to {target} rate.",
            )

        raw_rate = rates[target]
        if isinstance(raw_rate, bool) or not isinstance(raw_rate, (int, float, str)):
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned a rate that is not a number.",
                status_code=502,
            )
        try:
            rate = Decimal(str(raw_rate))
        except InvalidOperation:
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned a rate that is not a number.",
                status_code=502,
            ) from None
        if not rate.is_finite() or rate <= 0:
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned a rate that is not usable.",
                status_code=502,
            )

        # The date the rate belongs to is not ours to guess: the upstream sends
        # it, and a response without it cannot be answered honestly.
        raw_date = payload.get("date")
        if not isinstance(raw_date, str):
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned a rate with no date attached.",
                status_code=502,
            )
        try:
            rate_date = date.fromisoformat(raw_date)
        except ValueError:
            raise FxError(
                "upstream_invalid_response",
                "The exchange-rate source returned a rate with an unreadable date.",
                status_code=502,
            ) from None

        return Quote(rate=rate, rate_date=rate_date)
