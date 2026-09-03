"""Input validation.

FastAPI's own validation would reject bad input with a `{"detail": [...]}`
body, which is not the error shape this tool promises, and it would happily
parse `amount` into a float. So the query parameters arrive as raw strings and
are parsed here: one place, one error shape, decimal arithmetic from the start.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from .errors import FxError

# The ECB reference series starts on 1999-01-04, the first business day of the
# euro. Nothing exists before it, so we say so instead of asking upstream.
ECB_SERIES_START = date(1999, 1, 4)

# Not a currency limit — a sanity limit. Above this the caller is not asking a
# real question, and the answer would be noise in a customer-facing sentence.
MAX_AMOUNT = Decimal("1000000000000")  # 1e12

_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

try:  # pragma: no cover - depends on the tzdata available on the host
    from zoneinfo import ZoneInfo

    _ECB_TZ: ZoneInfo | None = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    _ECB_TZ = None


def ecb_today() -> date:
    """Today in the ECB's own timezone.

    "Is this date in the future?" has to be answered where the rates are
    published, not where this process happens to run. Falls back to UTC if the
    host has no timezone database; the worst case is a one-day-wide window
    around midnight CET, which the future-date check treats conservatively.
    """
    if _ECB_TZ is not None:
        return datetime.now(_ECB_TZ).date()
    return datetime.now(timezone.utc).date()


def parse_amount(raw: str | None) -> Decimal:
    if raw is None or raw.strip() == "":
        raise FxError("invalid_amount", "The 'amount' parameter is required.")
    try:
        amount = Decimal(raw.strip())
    except InvalidOperation:
        raise FxError(
            "invalid_amount",
            f"'{raw}' is not a number. Send amount as a plain decimal, for example 250 or 250.75.",
        ) from None
    if not amount.is_finite():
        raise FxError("invalid_amount", "The 'amount' parameter must be a finite number.")
    if amount <= 0:
        raise FxError("invalid_amount", "The 'amount' parameter must be greater than zero.")
    if amount > MAX_AMOUNT:
        raise FxError(
            "invalid_amount",
            f"The 'amount' parameter must not exceed {MAX_AMOUNT:,.0f}.",
        )
    return amount


def parse_currency(raw: str | None, field: str) -> str:
    if raw is None or raw.strip() == "":
        raise FxError("invalid_currency", f"The '{field}' parameter is required.")
    code = raw.strip()
    if not _CURRENCY_RE.match(code):
        raise FxError(
            "invalid_currency",
            f"'{raw}' is not a currency code. Use a three-letter ISO 4217 code, for example EUR.",
        )
    return code.upper()


def parse_date(raw: str | None, today: date) -> date | None:
    """Parse the requested date, or None when the caller did not ask for one."""
    if raw is None or raw.strip() == "":
        return None
    text = raw.strip()
    if not _DATE_RE.match(text):
        raise FxError(
            "invalid_date",
            f"'{raw}' is not a date. Use the format YYYY-MM-DD, for example 2026-08-28.",
        )
    try:
        asked = date.fromisoformat(text)
    except ValueError:
        raise FxError(
            "invalid_date",
            f"'{raw}' is not a real calendar date.",
        ) from None
    if asked > today:
        raise FxError(
            "date_in_future",
            f"No rate exists for {asked.isoformat()} yet; the ECB has not published it. "
            f"The latest available date is on or before {today.isoformat()}.",
        )
    if asked < ECB_SERIES_START:
        raise FxError(
            "date_out_of_range",
            f"The ECB reference series starts on {ECB_SERIES_START.isoformat()}, "
            f"so no rate exists for {asked.isoformat()}.",
        )
    return asked
