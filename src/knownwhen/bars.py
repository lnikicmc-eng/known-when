"""Latest completed minute versions that were available at a decision time."""

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from knownwhen._time import delay, text, timestamp

BAR_VALUES = ("open", "high", "low", "close", "volume", "trade_count", "vwap")


@dataclass(frozen=True)
class BarPolicy:
    provider: str
    availability_basis: str = "recorded"
    processing_delay: timedelta = timedelta(0)
    assumed_delivery_delay: timedelta = timedelta(0)

    def __post_init__(self):
        text(self.provider, "provider")
        if self.availability_basis not in {"recorded", "bar_end_assumed"}:
            raise ValueError("Unsupported minute availability basis")
        delay(self.processing_delay, "processing_delay")
        delay(self.assumed_delivery_delay, "assumed_delivery_delay")
        if self.availability_basis == "recorded" and self.assumed_delivery_delay:
            raise ValueError("Recorded receipts cannot also use an assumed delivery delay")

    def to_dict(self):
        return {
            "provider": self.provider,
            "price_basis": "raw_nominal",
            "bar_minutes": 1,
            "availability_basis": self.availability_basis,
            "processing_delay_seconds": self.processing_delay.total_seconds(),
            "assumed_delivery_delay_seconds": self.assumed_delivery_delay.total_seconds(),
            "missingness": "no filling; invalid latest payloads retained",
        }


def completed_bars(bars, *, symbol, start, end, decision, policy):
    """Return latest eligible snapshots for minute starts in [start,end).

    This selects versions; it does not repair gaps or validate price payloads.
    Invalid latest values remain invalid instead of falling back to an older value.
    DataFrame.attrs['knownwhen_policy'] records whether availability was assumed;
    use the CLI's JSON envelope when exporting to preserve that distinction.
    """
    start, end, decision = map(timestamp, (start, end, decision))
    if start > end or end > decision or start != start.floor("min") or end != end.floor("min"):
        raise ValueError("Increasing completed whole-minute interval required")
    text(symbol, "symbol")
    if symbol != symbol.strip().upper():
        raise ValueError("Explicit uppercase symbol required")
    fields = ["symbol", "bar_start", "provider", "price_basis", *BAR_VALUES]
    if policy.availability_basis == "recorded":
        fields.append("available_at")
    if set(fields) - set(bars):
        raise ValueError("Complete nominal snapshot/availability schema required")
    selected = bars.loc[bars.symbol.eq(symbol), fields].copy()
    selected["bar_start"] = pd.to_datetime([timestamp(v) for v in selected.bar_start], utc=True)
    selected = selected.loc[(selected.bar_start >= start) & (selected.bar_start < end)].copy()
    completed = selected.bar_start + pd.Timedelta(minutes=1)
    if policy.availability_basis == "recorded":
        ready = pd.Series(
            pd.to_datetime([timestamp(v) for v in selected.available_at], utc=True),
            index=selected.index,
        )
        selected["available_at"] = ready
    else:
        ready = completed + policy.assumed_delivery_delay
    selected["_ready_at"] = ready + policy.processing_delay
    selected = selected.loc[selected["_ready_at"] <= decision].copy()
    if not selected.empty:
        if (
            not selected.bar_start.eq(selected.bar_start.dt.floor("min")).all()
            or set(selected.provider) != {policy.provider}
            or set(selected.price_basis) != {"raw_nominal"}
            or (
                selected["_ready_at"] - policy.processing_delay
                < selected.bar_start + pd.Timedelta(minutes=1)
            ).any()
        ):
            raise ValueError("Nominal source/completion metadata differs")
        latest = selected.groupby("bar_start")["_ready_at"].transform("max")
        selected = selected.loc[selected["_ready_at"].eq(latest)].drop_duplicates()
        if selected.bar_start.duplicated().any():
            raise ValueError("Conflicting latest available minute snapshots")
    result = selected.sort_values("bar_start").reset_index(drop=True)
    result.attrs["knownwhen_policy"] = policy.to_dict()
    return result
