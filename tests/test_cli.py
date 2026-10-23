import hashlib
import json
from pathlib import Path

import pytest

from knownwhen.cli import main
from knownwhen.demo import demo_timeline


@pytest.mark.parametrize("mutation", ["extra", "short", "quote", "empty_header"])
def test_malformed_csv_structure_is_rejected(tmp_path, capsys, mutation):
    lines = (Path(__file__).parents[1] / "examples" / "bars.csv").read_text().splitlines()
    if mutation == "extra":
        lines[1] += ",extra"
    elif mutation == "short":
        lines[1] = lines[1].rsplit(",", 1)[0]
    elif mutation == "quote":
        lines[1] = '"unterminated'
    else:
        lines[0] = lines[0].replace("symbol,", ",", 1)
    source = tmp_path / "bad.csv"
    source.write_text("\n".join(lines) + "\n")
    output = tmp_path / "out.json"
    assert (
        main(
            [
                "bars",
                "--input",
                str(source),
                "--provider",
                "demo",
                "--symbol",
                "SYNTH",
                "--at",
                "2020-01-02T14:32:00Z",
                "--start",
                "2020-01-02T14:30:00Z",
                "--end",
                "2020-01-02T14:31:00Z",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
    assert "CSV" in capsys.readouterr().err


def test_demo_is_synthetic_and_revision_aware(capsys):
    assert main(["demo"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["synthetic_only"] is True
    assert result["before_correction"]["stories"][0]["revision_id"] == "v1"
    assert result["after_correction"]["stories"][0]["revision_id"] == "v2"


def test_news_output_is_exclusive_and_existing_input_preserved(tmp_path):
    source, output = tmp_path / "news.jsonl", tmp_path / "result.json"
    digest = demo_timeline().write_new(source)
    args = [
        "news",
        "--input",
        str(source),
        "--sha256",
        digest,
        "--provider",
        "demo",
        "--symbol",
        "SYNTH",
        "--at",
        "2020-01-02T14:10:00Z",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    original = output.read_bytes()
    assert main(args) == 2 and output.read_bytes() == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("tail", [', "kind":"revision"', ', "extra":NaN', ', "extra":Infinity'])
def test_duplicate_or_nonfinite_json_is_rejected(tmp_path, tail):
    source = tmp_path / "bad.jsonl"
    demo_timeline().write_new(source)
    line = source.read_text().splitlines()[0]
    material = (line[:-1] + tail + "}\n").encode()
    source.write_bytes(material)
    assert (
        main(
            [
                "news",
                "--input",
                str(source),
                "--sha256",
                hashlib.sha256(material).hexdigest(),
                "--provider",
                "demo",
                "--symbol",
                "SYNTH",
                "--at",
                "2020-01-02T14:10:00Z",
            ]
        )
        == 2
    )


def test_clearing_correction_suppresses_every_old_symbol():
    from dataclasses import replace

    from knownwhen import NewsPolicy, NewsTimeline

    old, new = demo_timeline().revisions
    cleared = NewsTimeline([old, replace(new, symbols=())])
    assert (
        cleared.snapshot("SYNTH", "2020-01-02T14:30:00Z", NewsPolicy(("demo",)))["story_count"] == 0
    )


def test_bar_export_records_assumed_policy(tmp_path, capsys):
    source = tmp_path / "bars.csv"
    source.write_text(
        "symbol,bar_start,provider,price_basis,open,high,low,close,volume,trade_count,vwap\n"
        "SYNTH,2020-01-02T14:30:00Z,demo,raw_nominal,100,101,99,100,1000,20,100\n"
    )
    assert (
        main(
            [
                "bars",
                "--input",
                str(source),
                "--provider",
                "demo",
                "--symbol",
                "SYNTH",
                "--at",
                "2020-01-02T14:32:00Z",
                "--start",
                "2020-01-02T14:30:00Z",
                "--end",
                "2020-01-02T14:31:00Z",
                "--availability-basis",
                "bar_end_assumed",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["policy"]["availability_basis"] == "bar_end_assumed"
    assert len(result["bars"]) == 1 and result["price_payload_validated"] is False


def test_duplicate_csv_header_is_rejected(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("symbol,symbol\nSYNTH,SYNTH\n")
    assert (
        main(
            [
                "bars",
                "--input",
                str(source),
                "--provider",
                "demo",
                "--symbol",
                "SYNTH",
                "--at",
                "2020-01-02T14:32:00Z",
                "--start",
                "2020-01-02T14:30:00Z",
                "--end",
                "2020-01-02T14:31:00Z",
            ]
        )
        == 2
    )
