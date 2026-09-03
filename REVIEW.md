# Review of tool.py

It runs, and that is the problem: every defect below returns HTTP 200 with a
plausible-looking number. Nothing here fails loudly.

I checked each finding by running `tool.py` against a local stub upstream —
which required patching `tool.UPSTREAM` at runtime, since the host is a literal
in the module (finding 5). Observed values are quoted below.

## 1. The cache is keyed on the currency pair only, so it serves one rate for every date — forever

`_cache[f"{base}-{target}"]` ignores the date, and the hit path returns
`_cache[key], str(on or date.today())`: the first rate ever fetched for a pair,
labelled with whatever date the current caller asked for. It has no expiry
either, so a process that has run since yesterday still serves yesterday's rate
as today's.

**To the customer:** they are told a confident, wrong number. One historical
question poisons every later answer for that pair. Observed: after a request for
`2020-01-02` (stub rate 6.7), the very next request for the latest rate returned
`rate: 6.7, result: 1675.0, rate_date: "2026-09-03"` — the customer is quoted
1 675 TRY for 250 EUR instead of ≈11 780. Nothing in the response hints at it.

**How I verified:** two requests in one process, different dates, same pair;
compared `rate` against the stub's per-date rates. As a regression test: two
`GET`s with different `date` values must produce two upstream calls and two
different rates.

## 2. Every failure is caught and returned as a successful conversion of 0.00

The `except Exception` in `convert` returns 200 with `rate: 0.0`,
`result: 0.0` and the same field names as a real answer. Timeouts, a 500, an
HTML error page, a missing symbol — all become a zero the caller cannot
distinguish from a rate.

**To the customer:** "250 EUR is 0.00 TRY." Worse, the agent has no signal to
retry or apologise, and our monitoring sees a healthy 200. Observed with the
upstream pointed at a closed port: `{"rate": 0.0, "result": 0.0, ...}`, status
200, with `conversion failed: ...` printed to stdout where nobody reads it.

**How I verified:** point `UPSTREAM` at a closed port and call the endpoint;
assert the status is non-2xx. Same for a stub returning 500 and one returning
HTML.

## 3. `rate_date` is asserted by us, never read from the upstream

`fetch_rate` returns `str(on or date.today())` — the date the *caller* asked
for. The upstream's own `date` field, which says which day the rate is really
from, is never read. The weekend branch makes it explicit: it re-fetches
`/latest` and still labels the result with the requested date.

**To the customer:** on a Sunday they are told "the rate on 30 August was
47.1234" when that is Friday's rate. It is presented as fact, so the agent
repeats it as fact. Observed: `on=2026-08-30` returned `rate_date:
"2026-08-30"` while the stub's payload said `"date": "2026-08-28"`. A future
date behaves the same way — `on=2030-01-01` returned today's rate stamped
`rate_date: "2030-01-01"`.

**How I verified:** request a Saturday and a future date, and compare
`rate_date` in the response against `date` in the upstream payload. They must
match.

## 4. The documented query contract is not the one the code accepts

The brief's tool call is `?amount=250&from=EUR&to=TRY&date=2026-08-28`, but the
signature is `from_`, `to`, `on`. FastAPI ignores unknown query parameters, so
`from=USD` and `date=...` are silently dropped and the defaults `EUR`/latest are
used instead.

**To the customer:** they ask to convert **USD** to JPY and are quoted a **EUR**
conversion. Observed for the URL exactly as written in the brief with
`from=USD&to=JPY`: `{"from": "EUR", "to": "JPY", "rate_date": "2026-09-03"}` —
wrong source currency, wrong date, status 200. Separately, `amount=abc` returns
FastAPI's `{"detail": [...]}` (422), not the `{"error", "message"}` shape the
agent is built to read.

**How I verified:** call the URL from the brief verbatim and assert `from` in
the response equals what was asked; call with `amount=abc` and assert the error
body has `error` and `message` keys.

## Smaller, still real

- **`rate = round(rate, 2)` before multiplying.** Rounding the *rate* rather
  than only the result loses money: 1 000 000 EUR at 47.1234 returned
  47 120 000.00 instead of 47 123 400.00 — 3 400 TRY short. For a pair whose
  rate is below 0.005 it rounds to zero, and the result with it. Verify by
  comparing against `Decimal` arithmetic on the unrounded rate.
- **No input validation.** `amount=-250` returned `result: -1675.0`, happily.
  Zero, `from == to` (which 404s upstream, then becomes 0.00 via finding 2) and
  out-of-range dates are all unhandled.
- **`UPSTREAM` and the port are literals.** The host cannot be pointed at a
  staging or fake upstream without editing the file, and the service ignores
  `PORT`. This is what forced me to monkey-patch the module to review it.
- **`print()` instead of logging**, and the caught exception is discarded after
  printing, so the only record of a failure is a line on stdout.
- **The cache is unbounded**, so distinct pairs accumulate for the life of the
  process. Minor next to finding 1, but it is the same dictionary.

## The one I would fix before shipping tonight

**Finding 1 — the cache key.** Findings 2 and 3 need a broken upstream or an
unusual date to hurt anyone; finding 1 hurts on a completely ordinary Tuesday,
with a healthy upstream and valid input, and it is the most believable wrong
number of the set. The minimum honest fix is to key the cache on
`(base, target, date_or_"latest")`, store the upstream's own date alongside the
rate, and give the "latest" entry a short TTL. If I could only ship one line, I
would delete the cache entirely — an extra upstream call is cheaper than a
7×-wrong number.

## Things that look suspicious but are fine

- **`httpx.AsyncClient()` created at import time, outside an event loop.** This
  is safe: httpx binds no loop at construction, and one shared client is the
  right call — a per-request client would throw away connection pooling. It is
  never closed, which produces a warning at shutdown, not a customer problem.
- **No explicit timeout.** httpx applies a 5 s default to connect, read, write
  and pool, so requests do not hang forever. Worth stating explicitly, but it
  is not the bug it looks like.
- **`/health` returns `{"ok": true}` without checking the upstream.** Correct
  for a liveness probe: an upstream outage should not get the container
  restarted. A readiness probe would be a separate endpoint.
- **`from __future__ import annotations` together with FastAPI.** It can break
  Pydantic's ability to resolve annotations, but every type used here
  (`float`, `str`, `date`, `dict`) resolves fine.
- **Falling back to an older published rate at all.** The weekend fallback is
  the right product decision — the ECB does not publish on weekends, and
  refusing would break the tool every Sunday. The defect is not the fallback,
  it is that finding 3 hides which day the number came from.
