# Known When

**Replay the information that was available then, rather than silently using today's revisions.**

Known When is a small Python toolkit for point-in-time news and completed-minute
candle snapshots. It handles article corrections, receipt and processing delays,
exact-text duplicates, missing coverage and late candle revisions.

## Why we are opening this work

We encountered these problems while building a private trading-research system.
Every time a researcher or AI assistant rebuilds the same timing checks, someone
spends time and AI usage solving an already encountered problem. We want those
solutions to become reusable public tools with tests and concrete examples.

This is the beginning of an ongoing release effort. As the research produces
useful general-purpose tools, fixes and improvements, we intend to publish and
maintain them. The aim is to help others build their own systems with less
repeated debugging and AI-assisted implementation. Savings have not yet been
benchmarked, and this early project makes no claim of existing community adoption.

## The problem in one timeline

```text
14:00:00  Article published
14:00:03  This system receives version 1
14:10:00  Research decision: version 1 is available
14:20:00  Corrected version 2 arrives
```

Reading the latest article into the 14:10 decision would leak the correction.
Known When retains both versions and selects only the eligible version.

## Try it

Python 3.11+ and pandas 2.2-2.x are required. Run from this repository:

```bash
python -m pip install .
python -m knownwhen demo
```

The offline demo uses entirely fictional records. It shows version 1 before the
correction, version 2 afterwards, and why an empty archive means UNKNOWN unless
the caller supplies timely, complete coverage evidence.

For CSV candle versions:

```bash
python -m knownwhen bars --input examples/bars.csv --provider demo --symbol SYNTH --start 2020-01-02T14:30:00Z --end 2020-01-02T14:31:00Z --at 2020-01-02T14:31:05Z
```

For the news archive, obtain its expected SHA-256 from `examples/manifest.json`:

```bash
python -m knownwhen news --input examples/news.jsonl --sha256 EXPECTED_SHA256 --provider demo --symbol SYNTH --at 2020-01-02T14:10:00Z
```

`--output result.json` creates a new JSON file and refuses to overwrite an
existing path. Without it, JSON is written to the terminal. Inputs are never
edited. File inputs are limited to 16 MiB. Article text is data, never executable
instructions. There are no network clients, credentials, telemetry or accounts.

## Python API

```python
from knownwhen import NewsPolicy, NewsTimeline

archive = NewsTimeline.from_jsonl("examples/news.jsonl", expected_sha256=expected_hash)
snapshot = archive.snapshot("SYNTH", "2020-01-02T14:10:00Z", NewsPolicy(("demo",)))
```

Create news archives using immutable `NewsRevision` and `NewsCoverage` records
and `NewsTimeline.write_new`. The synthetic construction is in
`src/knownwhen/demo.py`. A correction can use an empty symbol tuple to remove
all earlier ticker associations. Duplicate deliveries are idempotent; conflicting
immutable identities are rejected. Duplicate JSON keys and NaN/Infinity are rejected.

`BarPolicy` and `completed_bars` select latest eligible receipts for minute starts
in `[start, end)`. Returned DataFrame attributes contain the availability policy;
the CLI preserves it in a JSON envelope when exporting. Gaps are not repaired.
Latest invalid values remain invalid instead of falling back to older values.

## Evidence and limits

- Timezones are mandatory. Publication, text-version, system receipt, archive
  ingestion and processing times are separate. `available_at` denotes the caller's
  recorded system receipt; `ingested_at` is when that version entered its archive.
- Historical publication-only news and bar-end-only candles require explicit
  assumption modes. They are not verified live availability.
- COVERED states mean caller-supplied coverage attestations structurally satisfy
  the contract. They do not independently verify a provider, its completeness or
  the truth/licensing of an article. UNKNOWN must not be treated as "no news".
- Duplicate text means exact headline/body equality, not semantic equivalence.
- The candle selector uses receipt order, not provider revision ordinals. It does
  not certify price validity, adjustment correctness, feed coverage or execution.
- News snapshots scan the in-memory archive; this is a small research utility,
  not a streaming database. The timing checks do not prove an entire backtest
  free of leakage or establish a profitable strategy.

## Development and maintenance

```bash
python -m pip install ".[dev]"
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
```

Bug reports should include a minimal synthetic reproduction, the expected clock
behavior and the installed version. Please exclude API keys, personal information
and provider-owned article archives. Improvements should include a regression
test and documentation. There is no fixed release schedule; useful, reviewed
improvements will be released as they become ready. MIT license.
