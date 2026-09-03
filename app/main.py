"""The HTTP surface: one tool endpoint and a health check.

The query parameters arrive as strings on purpose — see `validation.py`. Every
failure leaves through the same door, so the caller only ever sees a rate or an
`{"error", "message"}` object, never a framework's default error body.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from .cache import TTLCache
from .config import load_settings
from .errors import FxError
from .service import convert
from .upstream import FrankfurterClient, Quote
from .validation import ecb_today, parse_amount, parse_currency, parse_date

DESCRIPTION = """
Converts an amount between two currencies using European Central Bank
reference rates.

The rate returned always carries the date it actually belongs to. The ECB does
not publish on weekends or holidays: when the requested date has no rate, the
answer uses the last published one, `rate_date` shows that earlier date, and a
`note` says so. The service never invents a rate.
"""


def create_app(client: FrankfurterClient | None = None) -> FastAPI:
    """Build the app.

    `client` is injected by the tests so the suite can serve a fake upstream
    in-process and never open a socket.
    """
    settings = load_settings()
    owns_client = client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.upstream = client or FrankfurterClient(
            base_url=settings.upstream_base,
            timeout_seconds=settings.timeout_seconds,
        )
        app.state.cache = TTLCache[Quote]()
        try:
            yield
        finally:
            if owns_client:
                await app.state.upstream.aclose()

    app = FastAPI(
        title="fx-tool",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )

    @app.get(
        "/tools/convert",
        summary="Convert an amount between two currencies at an ECB reference rate",
    )
    async def convert_endpoint(
        request: Request,
        amount: str | None = Query(
            None, description="How much to convert. A positive decimal, e.g. 250 or 250.75."
        ),
        from_: str | None = Query(
            None, alias="from", description="Source currency, ISO 4217, e.g. EUR."
        ),
        to: str | None = Query(None, description="Target currency, ISO 4217, e.g. TRY."),
        date_: str | None = Query(
            None,
            alias="date",
            description="Optional date, YYYY-MM-DD. Defaults to the latest published rates.",
        ),
    ):
        try:
            today = ecb_today()
            parsed_amount = parse_amount(amount)
            base = parse_currency(from_, "from")
            target = parse_currency(to, "to")
            asked = parse_date(date_, today)

            payload = await convert(
                request.app.state.upstream,
                request.app.state.cache,
                amount=parsed_amount,
                base=base,
                target=target,
                asked=asked,
                today=today,
            )
            return JSONResponse(status_code=200, content=payload)
        except FxError as error:
            return JSONResponse(status_code=error.status_code, content=error.body())
        except Exception:  # pragma: no cover - the net under the net
            # Whatever this was, it is not a rate. Say nothing we cannot stand
            # behind: no number, no date.
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "This tool failed before it could produce a rate. No conversion was made.",
                },
            )

    @app.get("/health", summary="Liveness check")
    async def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
