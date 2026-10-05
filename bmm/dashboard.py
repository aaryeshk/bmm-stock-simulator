"""Numbers for Dashboard 1 ("Market now"), computed from a PriceHistory and the Nifty 50.

All prices are adjusted closes, the same series the trend engine and simulation use, so the
spot shown here is the S0 the paths start from.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from bmm.market import MarketStatus

# Trading-day windows for the momentum tiles (255-day year, as everywhere else).
WINDOWS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 255}


@dataclass(frozen=True)
class DayChange:
    price: float
    previous: float
    change: float
    pct: float
    date: date
    previous_date: date
    label: str            # "Today (delayed)" | "Last session, 01-Oct-2026"


@dataclass(frozen=True)
class Momentum:
    window: str
    days: int
    stock: float | None   # simple return over the window
    index: float | None   # Nifty 50 over the same dates
    relative: float | None  # stock - index, in return points


@dataclass(frozen=True)
class RangePosition:
    low: float
    high: float
    low_date: date
    high_date: date
    position: float       # 0 = at the 52-week low, 1 = at the high
    from_high: float      # spot / high - 1
    from_low: float       # spot / low - 1


def day_change(prices: pd.Series, status: MarketStatus | None = None,
               today: date | None = None) -> DayChange | None:
    prices = prices.dropna()
    if len(prices) < 2:
        return None
    last, prev = prices.iloc[-1], prices.iloc[-2]
    last_date, prev_date = prices.index[-1].date(), prices.index[-2].date()
    if status is not None and status.state == "open" and today is not None and last_date == today:
        label = "Today (delayed, session in progress)"
    else:
        label = f"Last session, {last_date:%d-%b-%Y}"
    return DayChange(float(last), float(prev), float(last - prev), float(last / prev - 1),
                     last_date, prev_date, label)


def range_52w(prices: pd.Series, days: int = 255) -> RangePosition:
    year = prices.dropna().iloc[-days:]
    spot, hi, lo = float(year.iloc[-1]), float(year.max()), float(year.min())
    return RangePosition(lo, hi, year.idxmin().date(), year.idxmax().date(),
                         (spot - lo) / (hi - lo) if hi > lo else 0.5, spot / hi - 1, spot / lo - 1)


def momentum(prices: pd.Series, index: pd.Series | None = None) -> list[Momentum]:
    """Simple returns over each window, and the Nifty 50 over the same calendar dates."""
    prices = prices.dropna()
    out = []
    for name, days in WINDOWS.items():
        if len(prices) <= days:
            out.append(Momentum(name, days, None, None, None))
            continue
        start = prices.index[-1 - days]
        stock = float(prices.iloc[-1] / prices.iloc[-1 - days] - 1)
        idx = None
        if index is not None:
            # Index level on the last date at or before each end of the window.
            sub = index.dropna()
            a, b = sub.loc[:start], sub.loc[:prices.index[-1]]
            if len(a) and len(b):
                idx = float(b.iloc[-1] / a.iloc[-1] - 1)
        out.append(Momentum(name, days, stock, idx, None if idx is None else stock - idx))
    return out


def chart_frame(prices: pd.Series, window_days: int | None = None) -> pd.DataFrame:
    """Long-format price + 50/200-day averages for the chart, trimmed to the last window."""
    df = pd.DataFrame({"Price": prices.dropna()})
    df["50-day average"] = df["Price"].rolling(50).mean()
    df["200-day average"] = df["Price"].rolling(200).mean()
    if window_days:
        df = df.iloc[-window_days:]
    long = df.reset_index(names="date").melt("date", var_name="series", value_name="value")
    return long.dropna()
