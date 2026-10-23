"""Synthetic completed-minute version selection contracts."""

from datetime import timedelta

import pandas as pd
import pytest

from knownwhen.bars import BarPolicy, completed_bars


def row(**changes):
    return dict(
        symbol="SYNTH",
        bar_start="2020-01-02T14:30:00Z",
        available_at="2020-01-02T14:31:01Z",
        provider="demo",
        price_basis="raw_nominal",
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1000,
        trade_count=20,
        vwap=100,
        **changes,
    )


def view(rows, at="2020-01-02T14:31:05Z", policy=None):
    return completed_bars(
        pd.DataFrame(rows),
        symbol="SYNTH",
        start="2020-01-02T14:30:00Z",
        end="2020-01-02T14:31:00Z",
        decision=at,
        policy=policy or BarPolicy("demo"),
    )


def test_late_correction_never_changes_earlier_snapshot():
    rows = [row(), {**row(), "available_at": "2020-01-02T14:31:30Z", "close": 102}]
    assert view(rows).close.tolist() == [100]
    assert view(rows, at="2020-01-02T14:31:30Z").close.tolist() == [102]
    rows[-1]["close"] = {"unavailable_future_payload": True}
    assert view(rows).close.tolist() == [100]


def test_latest_invalid_value_is_retained_never_replaced_with_older_value():
    rows = [row(), {**row(), "available_at": "2020-01-02T14:31:02Z", "close": None}]
    assert pd.isna(view(rows).close.iloc[0])


def test_identical_redelivery_and_ambiguous_latest_values():
    assert len(view([row(), row()])) == 1
    with pytest.raises(ValueError):
        view([row(), {**row(), "close": 101}])


def test_receipt_and_processing_must_follow_candle_completion():
    assert view(
        [row()],
        at="2020-01-02T14:31:02Z",
        policy=BarPolicy("demo", processing_delay=timedelta(seconds=2)),
    ).empty
    with pytest.raises(ValueError):
        view([{**row(), "available_at": "2020-01-02T14:30:59Z"}])


def test_assumptions_are_explicit_and_delayed():
    item = row()
    del item["available_at"]
    rules = BarPolicy(
        "demo", availability_basis="bar_end_assumed", assumed_delivery_delay=timedelta(seconds=30)
    )
    assert view([item], policy=rules).empty
    assert len(view([item], at="2020-01-02T14:31:30Z", policy=rules)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "wrong"},
        {"price_basis": "adjusted"},
        {"bar_start": "2020-01-02T14:30:01Z"},
    ],
)
def test_source_and_minute_boundary_are_enforced(changes):
    with pytest.raises(ValueError):
        view([{**row(), **changes}])
