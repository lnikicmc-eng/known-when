"""Immutable news versions with explicit receipt, processing and coverage clocks.

Evidence references are caller declarations. This module cannot independently
verify a provider's coverage, text history or licensing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from datetime import timedelta
from pathlib import Path

import pandas as pd

from knownwhen._time import delay, text, timestamp

SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 16 * 1024**2


def content_sha256(headline: str, body: str) -> str:
    """Hash exact text, without interpreting it or normalizing punctuation."""
    if not isinstance(headline, str) or not isinstance(body, str):
        raise TypeError("News headline and body must be strings")
    material = json.dumps([headline, body], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NewsRevision:
    provider: str
    story_id: str
    revision_id: str
    revision_number: int
    source: str
    symbols: tuple[str, ...]
    headline: str
    body: str
    published_at: object
    version_at: object
    available_at: object | None
    ingested_at: object
    availability_basis: str
    availability_evidence: str
    licence_reference: str
    symbol_mapping_reference: str
    content_sha256: str

    def __post_init__(self):
        for name in (
            "provider",
            "story_id",
            "revision_id",
            "source",
            "headline",
            "availability_evidence",
            "licence_reference",
            "symbol_mapping_reference",
        ):
            text(getattr(self, name), name)
        if type(self.revision_number) is not int or self.revision_number < 1:
            raise ValueError("revision_number must be a positive integer")
        # An explicit empty tuple is a correction removing every symbol association.
        if (
            not isinstance(self.symbols, tuple)
            or len(set(self.symbols)) != len(self.symbols)
            or any(not isinstance(s, str) or not s or s != s.strip().upper() for s in self.symbols)
        ):
            raise ValueError("symbols must be a tuple of distinct uppercase names, or empty")
        for name in ("published_at", "version_at", "ingested_at"):
            object.__setattr__(self, name, timestamp(getattr(self, name)))
        if not self.published_at <= self.version_at <= self.ingested_at:
            raise ValueError("Require publication <= text version <= archive ingestion")
        if self.availability_basis == "recorded":
            available = timestamp(self.available_at)
            if not self.version_at <= available <= self.ingested_at:
                raise ValueError("Require text version <= recorded receipt <= archive ingestion")
            object.__setattr__(self, "available_at", available)
        elif self.availability_basis == "publication_assumed":
            if self.available_at is not None:
                raise ValueError("Assumed availability must not supply a recorded receipt")
        else:
            raise ValueError("Unsupported availability_basis")
        if self.content_sha256 != content_sha256(self.headline, self.body):
            raise ValueError("Content SHA-256 differs from the exact revision text")


@dataclass(frozen=True)
class NewsCoverage:
    """Caller attestation of complete provider/symbol coverage over [start,end]."""

    provider: str
    symbol: str
    start: object
    end: object
    available_at: object
    evidence_reference: str
    licence_reference: str

    def __post_init__(self):
        for name in ("provider", "symbol", "evidence_reference", "licence_reference"):
            text(getattr(self, name), name)
        if self.symbol != self.symbol.strip().upper():
            raise ValueError("Coverage symbol must be uppercase")
        for name in ("start", "end", "available_at"):
            object.__setattr__(self, name, timestamp(getattr(self, name)))
        if not self.start <= self.end <= self.available_at:
            raise ValueError("Require coverage start <= end <= attestation availability")


@dataclass(frozen=True)
class NewsPolicy:
    providers: tuple[str, ...]
    lookback: timedelta = timedelta(hours=24)
    processing_delay: timedelta = timedelta(0)
    allow_publication_assumed: bool = False
    assumed_delivery_delay: timedelta = timedelta(0)

    def __post_init__(self):
        if (
            not isinstance(self.providers, tuple)
            or not self.providers
            or len(set(self.providers)) != len(self.providers)
        ):
            raise ValueError("Declare a non-empty tuple of distinct providers")
        for provider in self.providers:
            text(provider, "provider")
        for name in ("lookback", "processing_delay", "assumed_delivery_delay"):
            delay(getattr(self, name), name)
        if self.lookback <= timedelta(0) or type(self.allow_publication_assumed) is not bool:
            raise ValueError("Positive lookback and explicit boolean assumption flag required")
        if not self.allow_publication_assumed and self.assumed_delivery_delay:
            raise ValueError("An assumed delivery delay requires explicit assumption mode")

    def to_dict(self):
        return {
            "providers": list(self.providers),
            "lookback_seconds": self.lookback.total_seconds(),
            "processing_delay_seconds": self.processing_delay.total_seconds(),
            "allow_publication_assumed": self.allow_publication_assumed,
            "assumed_delivery_delay_seconds": self.assumed_delivery_delay.total_seconds(),
            "assumed_delivery_basis": "exact-text-version-at",
            "deduplication": "exact-text-first-ready-within-symbol-all-prior-history",
        }


@dataclass(frozen=True)
class VisibleNews:
    revision: NewsRevision
    ready_at: pd.Timestamp
    first_content_ready_at: pd.Timestamp
    duplicate: bool


class NewsTimeline:
    """Read-only archive. Later versions never replace earlier archived versions."""

    def __init__(
        self, revisions: Iterable[NewsRevision] = (), coverage: Iterable[NewsCoverage] = ()
    ):
        revisions, coverage = tuple(revisions), tuple(coverage)
        if any(not isinstance(r, NewsRevision) for r in revisions):
            raise ValueError("Expected NewsRevision records")
        if any(not isinstance(c, NewsCoverage) for c in coverage):
            raise ValueError("Expected NewsCoverage records")
        identities, sequence_ids = {}, {}
        for r in revisions:
            key = r.provider, r.story_id, r.revision_id
            sequence = r.provider, r.story_id, r.revision_number
            if key in identities and identities[key] != r:
                raise ValueError("Conflicting immutable news revision identity")
            if sequence in sequence_ids and sequence_ids[sequence] != key:
                raise ValueError("Ambiguous revision_number within a provider/story")
            identities[key], sequence_ids[sequence] = r, key
        self._revisions = tuple(identities.values())
        self._coverage = tuple(dict.fromkeys(coverage))

    @property
    def revisions(self):
        return self._revisions

    @property
    def coverage(self):
        return self._coverage

    @staticmethod
    def _ready(r, policy):
        if r.availability_basis == "recorded":
            return r.available_at + policy.processing_delay
        if policy.allow_publication_assumed:
            return r.version_at + policy.assumed_delivery_delay + policy.processing_delay
        return None

    def visible(self, symbol, cutoff, policy):
        cutoff = timestamp(cutoff)
        text(symbol, "symbol")
        if symbol != symbol.strip().upper():
            raise ValueError("Snapshot symbol must be uppercase")
        latest, first_content = {}, {}
        for r in self.revisions:
            if r.provider not in policy.providers:
                continue
            ready = self._ready(r, policy)
            if ready is None or ready > cutoff:
                continue
            key = r.provider, r.story_id
            if key not in latest or latest[key][0].revision_number < r.revision_number:
                latest[key] = r, ready
            if symbol in r.symbols:
                appearance = ready, r.provider, r.story_id, r.revision_number, r.revision_id
                first_content[r.content_sha256] = min(
                    first_content.get(r.content_sha256, appearance), appearance
                )
        rows = []
        for r, ready in latest.values():
            if symbol not in r.symbols or not cutoff - policy.lookback <= ready <= cutoff:
                continue
            first = first_content[r.content_sha256]
            identity = ready, r.provider, r.story_id, r.revision_number, r.revision_id
            rows.append(VisibleNews(r, ready, first[0], identity != first))
        return tuple(
            sorted(rows, key=lambda v: (v.ready_at, v.revision.provider, v.revision.story_id))
        )

    def _covered(self, provider, symbol, start, cutoff):
        spans = sorted(
            (c.start, c.end)
            for c in self.coverage
            if c.provider == provider and c.symbol == symbol and c.available_at <= cutoff
        )
        reached = None
        for first, last in spans:
            if last < start:
                continue
            if first > (start if reached is None else reached):
                return False
            reached = last if reached is None else max(reached, last)
            if reached >= cutoff:
                return True
        return False

    def snapshot(self, symbol, cutoff, policy):
        """Describe available records and declared coverage, without predicting anything."""
        cutoff = timestamp(cutoff)
        rows = self.visible(symbol, cutoff, policy)
        providers_covered = tuple(
            p
            for p in policy.providers
            if self._covered(p, symbol, cutoff - policy.lookback, cutoff)
        )
        assumed = sum(v.revision.availability_basis != "recorded" for v in rows)
        unproven = sum(
            r.availability_basis != "recorded"
            and r.provider in policy.providers
            and symbol in r.symbols
            and r.version_at <= cutoff
            and (policy.allow_publication_assumed or r.ingested_at <= cutoff)
            for r in self.revisions
        )
        pending = sum(
            r.availability_basis == "recorded"
            and r.provider in policy.providers
            and symbol in r.symbols
            and r.available_at <= cutoff < self._ready(r, policy)
            for r in self.revisions
        )
        covered = len(providers_covered) == len(policy.providers) and not unproven
        state = (
            ("COVERED_WITH_STORIES" if rows else "COVERED_PENDING" if pending else "COVERED_EMPTY")
            if covered
            else "UNKNOWN_WITH_STORIES"
            if rows
            else "UNKNOWN"
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "symbol": symbol,
            "cutoff": cutoff.isoformat(),
            "policy": policy.to_dict(),
            "coverage_state": state,
            "coverage_known": bool(covered),
            "coverage_basis": "caller-attested-not-independently-verified",
            "providers_covered": list(providers_covered),
            "assumed_revision_count": assumed,
            "unproven_revision_count": unproven,
            "pending_revision_count": pending,
            "story_count": len(rows),
            "distinct_content_count": len({v.revision.content_sha256 for v in rows}),
            "stories": [
                {
                    "provider": v.revision.provider,
                    "story_id": v.revision.story_id,
                    "revision_id": v.revision.revision_id,
                    "content_sha256": v.revision.content_sha256,
                    "published_at": v.revision.published_at.isoformat(),
                    "version_at": v.revision.version_at.isoformat(),
                    "ready_at": v.ready_at.isoformat(),
                    "first_content_ready_at": v.first_content_ready_at.isoformat(),
                    "duplicate": v.duplicate,
                    "availability_basis": v.revision.availability_basis,
                }
                for v in rows
            ],
        }

    def write_new(self, path):
        lines = []
        for kind, records in (("revision", self.revisions), ("coverage", self.coverage)):
            for record in records:
                row = {
                    key: value.isoformat() if isinstance(value, pd.Timestamp) else value
                    for key, value in asdict(record).items()
                }
                lines.append(
                    json.dumps(
                        {"schema_version": SCHEMA_VERSION, "kind": kind, **row},
                        ensure_ascii=False,
                        sort_keys=True,
                        allow_nan=False,
                    )
                )
        material = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        if len(material) > MAX_ARCHIVE_BYTES:
            raise ValueError("News archives are limited to 16 MiB")
        with Path(path).open("xb") as stream:
            stream.write(material)
        return hashlib.sha256(material).hexdigest()

    @classmethod
    def from_jsonl(cls, path, *, expected_sha256):
        with Path(path).open("rb") as stream:
            material = stream.read(MAX_ARCHIVE_BYTES + 1)
        if len(material) > MAX_ARCHIVE_BYTES:
            raise ValueError("News archives are limited to 16 MiB")
        if (
            not isinstance(expected_sha256, str)
            or hashlib.sha256(material).hexdigest() != expected_sha256.lower()
        ):
            raise ValueError("News archive SHA-256 does not match the expected source")
        revisions, coverage = [], []
        for number, line in enumerate(material.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, object_pairs_hook=_unique_keys, parse_constant=_nonfinite)
                if not isinstance(row, dict):
                    raise TypeError("Expected a JSON object")
                version = row.pop("schema_version")
                if type(version) is not int or version != SCHEMA_VERSION:
                    raise ValueError("Unsupported archive schema")
                kind = row.pop("kind")
                if kind not in {"revision", "coverage"}:
                    raise ValueError("Unsupported archive kind")
                record_type = NewsRevision if kind == "revision" else NewsCoverage
                if set(row) != {f.name for f in fields(record_type)}:
                    raise ValueError("Missing or unknown archive fields")
                if kind == "revision":
                    if not isinstance(row["symbols"], list):
                        raise ValueError("Archive symbols must be an array")
                    row["symbols"] = tuple(row["symbols"])
                    revisions.append(NewsRevision(**row))
                else:
                    coverage.append(NewsCoverage(**row))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ValueError(f"Invalid news archive record on line {number}") from exc
        return cls(revisions, coverage)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite JSON numbers are not supported")
