"""Fictional source records for an offline, reproducible demonstration."""

from dataclasses import replace

from knownwhen.news import NewsCoverage, NewsPolicy, NewsRevision, NewsTimeline, content_sha256


def demo_timeline():
    headline = "Synthetic company publishes an example update"
    old = NewsRevision(
        provider="demo",
        story_id="fictional-story",
        revision_id="v1",
        revision_number=1,
        source="synthetic",
        symbols=("SYNTH",),
        headline=headline,
        body="",
        published_at="2020-01-02T14:00:00Z",
        version_at="2020-01-02T14:00:00Z",
        available_at="2020-01-02T14:00:03Z",
        ingested_at="2020-01-02T14:00:03Z",
        availability_basis="recorded",
        availability_evidence="fictional receipt",
        licence_reference="synthetic example",
        symbol_mapping_reference="fictional mapping",
        content_sha256=content_sha256(headline, ""),
    )
    headline = "Synthetic company corrects the example update"
    new = replace(
        old,
        revision_id="v2",
        revision_number=2,
        headline=headline,
        version_at="2020-01-02T14:20:00Z",
        available_at="2020-01-02T14:20:00Z",
        ingested_at="2020-01-02T14:20:00Z",
        content_sha256=content_sha256(headline, ""),
    )
    return NewsTimeline([old, new])


def demo_result():
    timeline = demo_timeline()
    policy = NewsPolicy(("demo",))
    coverage = NewsCoverage(
        "demo",
        "SYNTH",
        "2020-01-01T15:00:00Z",
        "2020-01-02T15:00:00Z",
        "2020-01-02T15:00:00Z",
        "fictional complete stream",
        "synthetic",
    )
    return {
        "synthetic_only": True,
        "before_correction": timeline.snapshot("SYNTH", "2020-01-02T14:10:00Z", policy),
        "after_correction": timeline.snapshot("SYNTH", "2020-01-02T14:30:00Z", policy),
        "unknown_empty": NewsTimeline().snapshot("SYNTH", "2020-01-02T15:00:00Z", policy),
        "covered_empty": NewsTimeline(coverage=[coverage]).snapshot(
            "SYNTH", "2020-01-02T15:00:00Z", policy
        ),
    }
