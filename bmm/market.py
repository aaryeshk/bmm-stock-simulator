"""NSE market hours and holidays (IST), failing safe to "unknown" when the calendar lags.

NSE and BSE share equity trading holidays, so the BSE calendar (XBOM) from exchange_calendars is
used. Its holiday list is maintained a year or so ahead; past that, or on any error, the status
is "unknown" rather than a guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
OPEN, CLOSE = time(9, 15), time(15, 30)


@dataclass(frozen=True)
class MarketStatus:
    state: str                       # "open" | "closed" | "unknown"
    label: str                       # short text for the UI
    detail: str                      # one sentence of context
    last_close: date | None = None   # most recent session whose close has passed

    @property
    def known(self) -> bool:
        return self.state != "unknown"


@lru_cache(maxsize=1)
def _calendar():
    import exchange_calendars as xc

    return xc.get_calendar("XBOM")


def _unknown(why: str) -> MarketStatus:
    return MarketStatus("unknown", "Market status unknown", why)


def market_status(now: datetime | None = None) -> MarketStatus:
    try:
        return _status(now)
    except Exception as exc:  # any calendar problem: never crash the app over a status chip
        return _unknown(f"The NSE holiday calendar could not be read ({type(exc).__name__}).")


def _status(now: datetime | None) -> MarketStatus:
    now = (now or datetime.now(IST)).astimezone(IST)
    today, clock = now.date(), now.time()
    cal = _calendar()
    first, last = cal.first_session.date(), cal.last_session.date()
    if not first < today <= last:
        return _unknown(f"The NSE holiday calendar only runs to {last:%d-%b-%Y}.")

    def previous_session(d: date) -> date:
        return cal.date_to_session(pd.Timestamp(d), direction="previous").date()

    if cal.is_session(pd.Timestamp(today)):
        before = previous_session(today - pd.Timedelta(days=1))
        if clock < OPEN:
            return MarketStatus("closed", "Pre-open", "NSE opens at 09:15 IST today.", before)
        if clock < CLOSE:
            return MarketStatus("open", "Market open", "NSE closes at 15:30 IST. Prices are "
                                "delayed and today's candle is still forming.", before)
        return MarketStatus("closed", "Closed for the day", "NSE closed at 15:30 IST.", today)

    why = "weekend" if today.weekday() >= 5 else "NSE trading holiday"
    return MarketStatus("closed", f"Closed ({why})",
                        f"Today is a {why}. Showing the last session's close.",
                        previous_session(today))


def is_stale(last_price: date, status: MarketStatus) -> bool:
    """True when the data ends before the last completed session (only if the status is known)."""
    return status.known and status.last_close is not None and last_price < status.last_close
