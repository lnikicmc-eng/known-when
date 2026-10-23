"""Shared explicit-clock validation."""

from datetime import timedelta

import pandas as pd


def timestamp(value: object) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Timestamps must be present and timezone-aware") from exc
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("Timestamps must be present and timezone-aware")
    return result.tz_convert("UTC")


def text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def delay(value: object, name: str) -> None:
    if not isinstance(value, timedelta) or pd.isna(pd.Timedelta(value)) or value < timedelta(0):
        raise ValueError(f"{name} must be a finite nonnegative timedelta")
