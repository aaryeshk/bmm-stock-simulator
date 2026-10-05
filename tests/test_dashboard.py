import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bmm.dashboard import WINDOWS, chart_frame, day_change, momentum, range_52w
from bmm.market import MarketStatus

FIX = Path(__file__).parent / "fixtures"


def series(values, start="2026-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


# --- Day change ----------------------------------------------------------------------------------

def test_day_change_values():
    dc = day_change(series([100, 110, 99]))
    assert dc.price == 99 and dc.previous == 110
    assert dc.change == pytest.approx(-11) and dc.pct == pytest.approx(-0.1)
    assert dc.label.startswith("Last session, ")


def test_day_change_is_labelled_live_when_the_session_is_running():
    s = series([100, 101])
    open_ = MarketStatus("open", "Market open", "", None)
    assert "session in progress" in day_change(s, open_, today=s.index[-1].date()).label
    # Market open but the data's last bar is yesterday: not "today".
    assert day_change(s, open_, today=date(2030, 1, 1)).label.startswith("Last session")


def test_day_change_needs_two_prices():
    assert day_change(series([100])) is None


# --- 52-week range -------------------------------------------------------------------------------

def test_range_uses_only_the_last_255_days():
    s = series([500] + [100] * 254 + [150, 120])  # the 500 is 257 days back: out of range
    r = range_52w(s)
    assert r.high == 150 and r.low == 100
    assert r.position == pytest.approx(0.4)
    assert r.from_high == pytest.approx(120 / 150 - 1)
    assert r.high_date == s.index[-2].date()


def test_range_matches_the_class_sample():
    df = pd.read_csv(FIX / "class_reliance_nifty.csv", index_col="date", parse_dates=["date"])
    expected = json.loads((FIX / "class_sample_inputs.json").read_text())
    r = range_52w(df["close"])
    assert r.high == pytest.approx(expected["high_52w"])          # Summary!B28 = 1592.3
    assert r.from_high == pytest.approx(expected["from_high"])    # Summary!B29 = -17.0%


def test_flat_range_is_mid():
    assert range_52w(series([100] * 10)).position == 0.5


# --- Momentum ------------------------------------------------------------------------------------

def test_momentum_windows_and_relative_return():
    n = 300
    stock = series(100 * np.exp(0.002 * np.arange(n)))
    index = series(1000 * np.exp(0.001 * np.arange(n)))
    out = {m.window: m for m in momentum(stock, index)}
    assert list(out) == list(WINDOWS)
    for name, days in WINDOWS.items():
        assert out[name].stock == pytest.approx(np.exp(0.002 * days) - 1)
        assert out[name].index == pytest.approx(np.exp(0.001 * days) - 1)
        assert out[name].relative == pytest.approx(out[name].stock - out[name].index)


def test_momentum_aligns_index_by_date_not_position():
    stock = series(np.linspace(100, 130, 300))
    index = series(np.linspace(1000, 1300, 300)).drop(stock.index[-22])  # index misses a day
    m = {m.window: m for m in momentum(stock, index)}["1M"]
    start = stock.index[-22]
    expected_start = index.loc[:start].iloc[-1]   # last index level on or before the start
    assert m.index == pytest.approx(index.iloc[-1] / expected_start - 1)


def test_momentum_without_enough_history_or_index():
    m = {m.window: m for m in momentum(series(np.linspace(100, 110, 100)))}
    assert m["1M"].stock is not None and m["1M"].index is None and m["1M"].relative is None
    assert m["6M"].stock is None and m["1Y"].stock is None


# --- Chart data ----------------------------------------------------------------------------------

def test_chart_frame_moving_averages_and_window():
    s = series(np.arange(1, 301))
    df = chart_frame(s, 255)
    wide = df.pivot(index="date", columns="series", values="value")
    assert len(wide) == 255 and wide.index[-1] == s.index[-1]
    assert wide["50-day average"].iloc[-1] == pytest.approx(np.arange(251, 301).mean())
    assert wide["200-day average"].iloc[-1] == pytest.approx(np.arange(101, 301).mean())
    assert not df["value"].isna().any()


def test_chart_frame_short_history_has_no_200_day_line():
    df = chart_frame(series(np.arange(1, 120)))
    assert set(df["series"]) == {"Price", "50-day average"}
