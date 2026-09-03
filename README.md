# fx-tool

A currency conversion endpoint an AI agent can call as a tool. It answers from
European Central Bank reference rates via [frankfurter.dev](https://frankfurter.dev).

The caller is a language model talking to a paying customer, so the whole
service is built around one rule: **it may return a rate, or an error, and
nothing in between.** It never invents a number, and it never presents a rate
as belonging to a date it does not belong to.

## Run it

```bash
./run.sh                                   # http://localhost:8080
PORT=9000 FX_UPSTREAM_BASE=http://localhost:9001 ./run.sh
```

`run.sh` creates `.venv`, installs `requirements.txt` and starts uvicorn.

| Environment variable | Default | |
|---|---|---|
| `FX_UPSTREAM_BASE` | `https://api.frankfurter.dev` | Upstream host. The service calls `$FX_UPSTREAM_BASE/v1/{date\|latest}`. Only `app/config.py` mentions the real host, and only as this default. |
| `PORT` | `8080` | Port to listen on. |
| `FX_TIMEOUT_SECONDS` | `5` | Upstream timeout (2 s of it for connecting). |

## Test it

```bash
./test.sh
```

60 tests, no network. The upstream is served in-process by an
`httpx.MockTransport`, so the suite never opens a socket and passes with
`FX_UPSTREAM_BASE` pointing anywhere — including a closed port.

## The endpoint

```
GET /tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28
```

`date` is optional; without it you get the latest published rates. `GET /health`
returns `{"ok": true}`.

```json
{
  "amount": 250,
  "from": "EUR",
  "to": "TRY",
  "rate": 47.1234,
  "result": 11780.85,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-28",
  "source": "ECB via frankfurter.dev"
}
```

`rate_date` is the date the rate actually belongs to, taken from the upstream's
own `date` field. `asked_date` is what the caller asked for. **When they differ,
the response carries an extra `note` field** saying so in a sentence the model
can read out:

```json
{
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-30",
  "note": "The ECB published no rate for 2026-08-30. This result uses the rate published on 2026-08-28."
}
```

Errors are always `{"error": "<code>", "message": "<a sentence>"}` with a
non-2xx status — including for bad input, where FastAPI's own `{"detail": [...]}`
body would otherwise leak out.

## Error codes

| Code | Status | When |
|---|---|---|
| `invalid_amount` | 400 | `amount` missing, empty, not a number, `NaN`/`Infinity`, zero, negative, or above 1e12 |
| `invalid_currency` | 400 | `from`/`to` missing or not three letters |
| `invalid_date` | 400 | `date` is not `YYYY-MM-DD`, or not a real calendar date |
| `date_in_future` | 400 | `date` is after today in the ECB's timezone |
| `date_out_of_range` | 400 | `date` is before 1999-01-04, where the ECB series starts |
| `unsupported_currency` | 400 | The upstream publishes no such pair |
| `no_rate_for_date` | 404 | The upstream has nothing for that pair on that date |
| `upstream_timeout` | 504 | The upstream did not answer in time |
| `upstream_unavailable` | 502 / 503 | The upstream is unreachable, returned 5xx, or is rate-limiting us |
| `upstream_invalid_response` | 502 | The upstream returned something that is not a usable, dated rate |
| `internal_error` | 500 | A bug we did not foresee. Still no number. |

## What it does in each case

| Situation | Answer |
|---|---|
| **Weekend or holiday** — no rate for that date | 200 with the last published rate, `rate_date` showing that earlier date, plus a `note`. The ECB simply does not publish on those days; refusing would make the tool useless every Sunday, and the difference between the two dates is visible in the response. |
| **Before ~16:00 CET**, so today's rate is not out yet | Same: the latest published rate, with a `note` naming its date. |
| **Date in the future** | 400 `date_in_future`, without asking the upstream. The upstream would answer with today's rate — which would be a rate under a date it does not belong to. |
| **Date before 1999-01-04** | 400 `date_out_of_range`, without asking the upstream. |
| **Unknown currency** | 400 `unsupported_currency` (404 `no_rate_for_date` when a date was given, since a bare upstream 404 does not say which of the two it is — the message names both). |
| **`from` equals `to`** | 200, `rate` 1.0, `source` `identity (no upstream rate involved)`. No upstream call: there is no ECB rate involved, so we do not claim one. |
| **Upstream slow / 500 / not JSON / missing fields** | 502 or 504 with an error code. Never a rate, never a zero. |
| **Upstream returns a rate dated *after* the day asked for** | 502 `upstream_invalid_response`. It cannot be the rate that was asked for. |
| **`amount` missing, zero, negative** | 400 `invalid_amount`, no upstream call. |
| **`amount` with ten decimal places** | Accepted. Parsed as a `Decimal`, so no float drift; only the result is rounded, to 2 decimals, half-up. |

## Shape of the code

```
app/config.py      environment → settings (the only place the real host appears)
app/validation.py  query strings → Decimal, currency codes, date
app/upstream.py    the only module that talks to the network
app/cache.py       small TTL + LRU cache
app/service.py     the conversion, and the rate_date / asked_date rule
app/main.py        the HTTP surface; every failure leaves through one door
```

`NOTES.md` has the decisions and what I would do next. `REVIEW.md` is Part B.
