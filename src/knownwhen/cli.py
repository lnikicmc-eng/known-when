"""Local file inputs and auditable JSON outputs; no network or broker adapters."""

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

from knownwhen.bars import BarPolicy, completed_bars
from knownwhen.demo import demo_result
from knownwhen.news import MAX_ARCHIVE_BYTES, NewsPolicy, NewsTimeline


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run fictional, offline examples")
    demo.add_argument("--output", type=Path)
    for name in ("news", "bars"):
        command = commands.add_parser(name)
        command.add_argument("--input", required=True, type=Path)
        command.add_argument("--provider", required=True)
        command.add_argument("--symbol", required=True)
        command.add_argument("--at", required=True)
        command.add_argument("--processing-delay-seconds", type=float, default=0)
        command.add_argument("--assumed-delivery-delay-seconds", type=float, default=0)
        command.add_argument("--output", type=Path)
        if name == "news":
            command.add_argument("--sha256", required=True)
            command.add_argument("--lookback-seconds", type=float, default=86400)
            command.add_argument("--assume-publication", action="store_true")
        else:
            command.add_argument("--start", required=True)
            command.add_argument("--end", required=True)
            command.add_argument(
                "--availability-basis", choices=("recorded", "bar_end_assumed"), default="recorded"
            )
    return root


def main(argv=None):
    options = parser().parse_args(argv)
    try:
        if options.command == "demo":
            result = demo_result()
        elif options.command == "news":
            timeline = NewsTimeline.from_jsonl(options.input, expected_sha256=options.sha256)
            policy = NewsPolicy(
                (options.provider,),
                lookback=timedelta(seconds=options.lookback_seconds),
                processing_delay=timedelta(seconds=options.processing_delay_seconds),
                allow_publication_assumed=options.assume_publication,
                assumed_delivery_delay=timedelta(seconds=options.assumed_delivery_delay_seconds),
            )
            result = timeline.snapshot(options.symbol, options.at, policy)
            result["source_sha256"] = options.sha256.lower()
        else:
            with options.input.open("rb") as stream:
                raw = stream.read(MAX_ARCHIVE_BYTES + 1)
            if len(raw) > MAX_ARCHIVE_BYTES:
                raise ValueError("CSV input is limited to 16 MiB")
            rows = csv.reader(io.StringIO(raw.decode("utf-8")), strict=True)
            header = next(rows, [])
            if (
                not header
                or any(not name.strip() for name in header)
                or len(set(header)) != len(header)
            ):
                raise ValueError("CSV headers must be nonempty and unique")
            try:
                for row in rows:
                    if row and len(row) != len(header):
                        raise ValueError(
                            f"CSV record at line {rows.line_num} has incorrect field count"
                        )
            except csv.Error as exc:
                raise ValueError(f"Malformed CSV: {exc}") from exc
            policy = BarPolicy(
                options.provider,
                availability_basis=options.availability_basis,
                processing_delay=timedelta(seconds=options.processing_delay_seconds),
                assumed_delivery_delay=timedelta(seconds=options.assumed_delivery_delay_seconds),
            )
            selected = completed_bars(
                pd.read_csv(io.BytesIO(raw)),
                symbol=options.symbol,
                start=options.start,
                end=options.end,
                decision=options.at,
                policy=policy,
            )
            result = {
                "schema_version": 1,
                "policy": policy.to_dict(),
                "symbol": options.symbol,
                "decision_at": pd.Timestamp(options.at).isoformat(),
                "interval": {"start": options.start, "end_exclusive": options.end},
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "price_payload_validated": False,
                "coverage_verified": False,
                "bars": json.loads(
                    selected.to_json(orient="records", date_format="iso", date_unit="ns")
                ),
            }
        serialized = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        if options.output:
            with options.output.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        else:
            print(serialized, end="")
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError, csv.Error) as exc:
        print(f"known-when: {exc}", file=sys.stderr)
        return 2
