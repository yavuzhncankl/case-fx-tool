# Notes

## Decisions

**When the ECB published no rate for the date asked, I answer — and I say which
day the number is from.** The ECB does not publish on weekends or holidays, and
does not publish today's rate until about 16:00 CET. Refusing those requests
would make the tool useless on roughly a third of all calendar days, so the
endpoint returns the last published rate, puts the upstream's own date in
`rate_date`, keeps the caller's date in `asked_date`, and adds a `note` field
when the two differ:

> "The ECB published no rate for 2026-08-30. This result uses the rate published
> on 2026-08-28."

The model gets both dates as data and one sentence it can read out. That is the
line I did not want to cross: answering is fine, quietly implying the number
belongs to the requested day is not.

**A future date is refused, not fallen back.** The upstream would happily answer
a future date with today's rate, which is exactly the failure above wearing a
different hat. Same for dates before 1999-01-04, where the series starts. Both
are rejected without an upstream call.

**`rate_date` always comes from the upstream payload, never from the request.**
And if the upstream returns a rate dated *after* the day asked for, I return
502 rather than use it — that answer cannot be true, whether it is an upstream
bug or a fake upstream.

**`from == to` is answered without asking anyone.** Rate 1.0, and `source` says
`identity (no upstream rate involved)` rather than crediting the ECB with a rate
it never published.

**Decimal, not float, and only the result is rounded** — half-up, to two
decimals. Rounding the rate before multiplying is a money bug, not a display
choice.

**One error shape, one exit door.** Query parameters arrive as strings and are
parsed by hand, because FastAPI's own validation would return
`{"detail": [...]}` — a body the calling agent is not built to read. Everything,
including an unforeseen bug, leaves as `{"error", "message"}` with a non-2xx
status. Error codes are listed in the README.

**Cache keyed on `(from, to, date-or-latest)`**, with the rate's real date
stored beside it: 24 h for a settled historical date, 10 minutes for "latest"
so the tool picks up the afternoon publication. Failures are never cached — a
bad moment is not a fact.

## With another day

- Per-currency minor units. Everything is rounded to two decimals; JPY has none
  and BHD has three, so the result is presented slightly wrong for those.
- Single-flight around the cache. Ten concurrent misses for the same pair make
  ten upstream calls today.
- Use the upstream's `/v1/currencies` list, cached daily, so an unknown currency
  is always `unsupported_currency` instead of sometimes `no_rate_for_date` — a
  bare upstream 404 does not say which of the two it is, and right now I guess
  from whether a date was given and name both possibilities in the message.
- Structured logging with a request id, instead of nothing. Right now a failure
  is visible to the caller but leaves no trace on our side.
- A contract test against the real upstream, run in CI on a schedule and kept
  out of `test.sh`, so a change in the upstream's payload shape is caught by us
  and not by a customer.

## AI tools

Claude Code, heavily. "I used AI" can mean very different things, so here is the
division of labour, plainly.

**What I decided.** The goal, and the trade-offs. On the weekend case I had the
options laid out — refuse, fall back silently, or fall back visibly — and chose
the third, because refusing breaks the tool on a third of the calendar and
falling back silently is the one thing the brief forbids. Same for refusing
future dates instead of letting the upstream answer them with today's rate. The
rule the whole service is built on is the one I would defend at a whiteboard:
answer what can be answered, say exactly what you are answering when it is not
the question asked, and return an error when nothing true is available.

**What the assistant wrote.** Essentially all of the code, the tests, and the
first drafts of these documents.

**What I did with it.** I did not sign off on code I could not explain. I went
through the request path module by module, then had the assistant put me through
an oral exam on my own submission — its questions, my answers, no looking at the
code. That is how I found the parts I had accepted without understanding. Two
examples: I could not say how many upstream calls a future-dated request makes
(the answer is zero — `parse_date` rejects it before anything is asked), and I
had the wrong reason for parsing `amount` by hand (it is the error-body shape and
`Decimal`, not any distrust of FastAPI's parsing). I went back to both.

Then I ran it rather than trusting it: the suite on my own machine (Windows,
Python 3.13, 60 passing), and the real service against the live Frankfurter API,
checking six cases by hand. One of them was accidental proof that the design
matters — asked on 3 September before the ECB's afternoon publication, the
service returned the 2 September rate and said so, which is exactly the case
`tool.py` mislabels.

## One thing the AI got wrong

The `note` field. When a caller passes no date at all, the first version still
produced *"The ECB published no rate for 2026-09-03"* — but nobody had asked
about 2026-09-03; they asked for the latest rate. The sentence invented a
question in order to apologise for it, and an agent reading it to a customer
would have sounded confused.

To be accurate about who caught it: the assistant did, when it started the
service against a local stub and read the response, not me. What I take from it
is the part that matters anyway — **the test was the real defect.** It asserted
only that a `note` existed, so the wording could be nonsense and still pass. The
fix pinned the exact sentence. For a field a language model is going to read out
loud to a customer, the wording *is* the behaviour, and a test that does not
assert it is not testing anything.