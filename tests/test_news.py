"""Synthetic timing contracts, without market history or model expectations."""

from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest

from knownwhen.news import NewsCoverage, NewsPolicy, NewsRevision, NewsTimeline, content_sha256


def stamp(clock):
    return pd.Timestamp(f"2020-01-02T{clock}Z")


def revision(story="story", number=1, clock="14:00:03", headline="Synthetic update", **changes):
    values = {
        "provider": "demo",
        "story_id": story,
        "revision_id": f"v{number}",
        "revision_number": number,
        "source": "synthetic",
        "symbols": ("SYNTH",),
        "headline": headline,
        "body": "",
        "published_at": stamp("14:00:00"),
        "version_at": stamp(clock) if number > 1 else stamp("14:00:00"),
        "available_at": stamp(clock),
        "ingested_at": stamp(clock),
        "availability_basis": "recorded",
        "availability_evidence": "synthetic receipt",
        "licence_reference": "synthetic text",
        "symbol_mapping_reference": "synthetic mapping",
        "content_sha256": content_sha256(headline, ""),
    }
    values.update(changes)
    return NewsRevision(**values)


def coverage(start="14:00:00", end="15:00:00", **changes):
    values = {
        "provider": "demo",
        "symbol": "SYNTH",
        "start": stamp(start),
        "end": stamp(end),
        "available_at": stamp(end),
        "evidence_reference": "synthetic complete feed",
        "licence_reference": "synthetic text",
    }
    values.update(changes)
    return NewsCoverage(**values)


def policy(**changes):
    return NewsPolicy(providers=("demo",), lookback=timedelta(hours=1), **changes)


def test_versions_wait_for_receipt_and_processing():
    original = revision()
    correction = revision(number=2, clock="14:20:00", headline="Synthetic correction")
    rules = policy(processing_delay=timedelta(seconds=2))
    timeline = NewsTimeline([original, correction])
    assert timeline.snapshot("SYNTH", stamp("14:00:04"), rules)["story_count"] == 0
    assert timeline.snapshot("SYNTH", stamp("14:00:05"), rules)["story_count"] == 1
    assert timeline.snapshot("SYNTH", stamp("14:20:01"), rules)["stories"][0]["revision_id"] == "v1"
    assert timeline.snapshot("SYNTH", stamp("14:20:02"), rules)["stories"][0]["revision_id"] == "v2"


def test_future_additions_never_change_an_earlier_strict_snapshot():
    original = revision()
    baseline = NewsTimeline([original]).snapshot("SYNTH", stamp("14:10:00"), policy())
    future = [revision(f"later-{i}", clock="14:30:00", headline=f"Synthetic {i}") for i in range(8)]
    for rows in ([original, *future], [*reversed(future), original]):
        assert (
            NewsTimeline(rows, [coverage()]).snapshot("SYNTH", stamp("14:10:00"), policy())
            == baseline
        )


def test_symbol_correction_and_out_of_order_delivery():
    correction = revision(number=2, clock="14:10:00", symbols=("OTHER",))
    timeline = NewsTimeline([correction, revision(clock="14:20:00")])
    assert timeline.snapshot("SYNTH", stamp("14:30:00"), policy())["story_count"] == 0
    assert (
        timeline.snapshot("OTHER", stamp("14:30:00"), policy())["stories"][0]["revision_id"] == "v2"
    )


def test_empty_is_unknown_without_complete_timely_coverage():
    at = stamp("15:00:00")
    assert NewsTimeline().snapshot("SYNTH", at, policy())["coverage_state"] == "UNKNOWN"
    complete = NewsTimeline(coverage=[coverage("14:00:00", "14:30:00"), coverage("14:30:00")])
    assert complete.snapshot("SYNTH", at, policy())["coverage_state"] == "COVERED_EMPTY"
    assert complete.snapshot("OTHER", at, policy())["coverage_state"] == "UNKNOWN"
    gap = NewsTimeline(coverage=[coverage("14:00:00", "14:30:00"), coverage("14:30:01")])
    assert gap.snapshot("SYNTH", at, policy())["coverage_state"] == "UNKNOWN"
    delayed = NewsTimeline(coverage=[coverage(available_at=stamp("15:00:01"))])
    assert delayed.snapshot("SYNTH", at, policy())["coverage_state"] == "UNKNOWN"
    assert not complete.snapshot("SYNTH", at, replace(policy(), providers=("demo", "other")))[
        "coverage_known"
    ]


def test_delivered_unprocessed_story_is_pending():
    timeline = NewsTimeline([revision(clock="15:00:00")], [coverage()])
    result = timeline.snapshot(
        "SYNTH", stamp("15:00:00"), policy(processing_delay=timedelta(seconds=2))
    )
    assert result["coverage_state"] == "COVERED_PENDING"
    assert result["pending_revision_count"] == 1 and result["story_count"] == 0


def test_assumed_availability_is_opt_in_never_declared_complete_and_not_backdated():
    assumed = revision(
        number=2,
        clock="14:20:00",
        availability_basis="publication_assumed",
        available_at=None,
        ingested_at=stamp("16:00:00"),
    )
    archive = NewsTimeline([revision(), assumed], [coverage()])
    strict = archive.snapshot("SYNTH", stamp("15:00:00"), policy())
    assert strict["stories"][0]["revision_id"] == "v1"
    optional = policy(allow_publication_assumed=True)
    assert (
        archive.snapshot("SYNTH", stamp("14:10:00"), optional)["stories"][0]["revision_id"] == "v1"
    )
    later = archive.snapshot("SYNTH", stamp("15:00:00"), optional)
    assert later["stories"][0]["revision_id"] == "v2"
    assert later["coverage_state"] == "UNKNOWN_WITH_STORIES"
    assert later["assumed_revision_count"] == 1


def test_duplicates_are_retained_but_marked_using_only_prior_exact_text():
    timeline = NewsTimeline([revision("second", clock="14:20:00"), revision("first")])
    result = timeline.snapshot("SYNTH", stamp("14:30:00"), policy())
    assert result["story_count"] == 2 and result["distinct_content_count"] == 1
    assert [s["duplicate"] for s in result["stories"]] == [False, True]
    assert "direction_mean" not in result and "profit_probability" not in result


def test_identity_conflicts_are_rejected_and_redelivery_is_idempotent():
    item = revision()
    assert len(NewsTimeline([item, item]).revisions) == 1
    with pytest.raises(ValueError):
        NewsTimeline([item, revision(headline="Different synthetic text")])
    with pytest.raises(ValueError):
        NewsTimeline([item, revision(revision_id="ambiguous")])


@pytest.mark.parametrize(
    "changes",
    [
        {"published_at": "2020-01-02T14:00:00"},
        {"version_at": stamp("13:59:59")},
        {"available_at": stamp("13:59:59")},
        {"symbols": ("synth",)},
        {"revision_number": True},
        {"content_sha256": "0" * 64},
        {"availability_basis": "guessed"},
    ],
)
def test_malformed_revision_metadata_is_rejected(changes):
    with pytest.raises(ValueError):
        revision(**changes)


def test_archive_roundtrip_hash_schema_and_no_overwrite(tmp_path):
    archive = NewsTimeline([revision()], [coverage()])
    target = tmp_path / "news.jsonl"
    digest = archive.write_new(target)
    restored = NewsTimeline.from_jsonl(target, expected_sha256=digest)
    assert restored.snapshot("SYNTH", stamp("15:00:00"), policy()) == archive.snapshot(
        "SYNTH", stamp("15:00:00"), policy()
    )
    with pytest.raises(FileExistsError):
        archive.write_new(target)
    with pytest.raises(ValueError):
        NewsTimeline.from_jsonl(target, expected_sha256="0" * 64)
