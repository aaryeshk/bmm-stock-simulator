from datetime import date, datetime

import pytest

from bmm import market
from bmm.market import IST, MarketStatus, is_stale, market_status


def at(y, m, d, hh=12, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_open_during_trading_hours():
    s = market_status(at(2026, 10, 5, 10, 0))  # Monday
    assert s.state == "open"
    assert s.last_close == date(2026, 10, 1)  # Fri 2 Oct was Gandhi Jayanti


def test_pre_open():
    s = market_status(at(2026, 10, 5, 9, 0))
    assert s.state == "closed" and s.label == "Pre-open"
    assert s.last_close == date(2026, 10, 1)


def test_after_close_counts_today():
    s = market_status(at(2026, 10, 5, 15, 30))
    assert s.state == "closed" and s.last_close == date(2026, 10, 5)


def test_weekend():
    s = market_status(at(2026, 10, 4))  # Sunday
    assert s.label == "Closed (weekend)" and s.last_close == date(2026, 10, 1)


def test_exchange_holiday():
    s = market_status(at(2026, 10, 2))  # Gandhi Jayanti
    assert s.label == "Closed (NSE trading holiday)" and s.last_close == date(2026, 10, 1)


def test_utc_input_is_converted_to_ist():
    from datetime import UTC
    s = market_status(datetime(2026, 10, 5, 4, 0, tzinfo=UTC))  # 09:30 IST
    assert s.state == "open"


def test_beyond_the_calendar_is_unknown_not_a_guess():
    s = market_status(at(2031, 1, 6))
    assert s.state == "unknown" and not s.known
    assert "only runs to" in s.detail


def test_calendar_failure_is_unknown(monkeypatch):
    def broken():
        raise RuntimeError("calendar package missing")

    monkeypatch.setattr(market, "_calendar", broken)
    s = market_status(at(2026, 10, 5))
    assert s.state == "unknown" and "RuntimeError" in s.detail


@pytest.mark.parametrize("last_price,expected", [(date(2026, 9, 30), True),
                                                 (date(2026, 10, 1), False)])
def test_staleness(last_price, expected):
    assert is_stale(last_price, market_status(at(2026, 10, 4))) is expected


def test_unknown_status_never_claims_staleness():
    assert not is_stale(date(2020, 1, 1), MarketStatus("unknown", "", ""))
