import numpy as np
import pandas as pd
import pytest

from bmm import cache, data
from bmm.data import (
    DataUnavailable,
    UploadError,
    clean_prices,
    get_index_prices,
    get_prices,
    parse_upload,
)


def synthetic(days=300, start="2024-10-01", price=100.0):
    idx = pd.bdate_range(start, periods=days)
    closes = price * np.exp(np.cumsum(np.full(days, 0.001)))
    return pd.DataFrame({"close": closes, "adj_close": closes}, index=idx)


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "SNAPSHOT_DIR", tmp_path)
    return tmp_path


# --- Cleaning ----------------------------------------------------------------------------------

def test_clean_prices_sorts_dedupes_and_drops_bad_rows():
    idx = pd.DatetimeIndex(["2026-01-02 00:00+05:30", "2026-01-01 00:00+05:30",
                            "2026-01-02 00:00+05:30", "2026-01-05 00:00+05:30",
                            "2026-01-06 00:00+05:30"])
    df = pd.DataFrame({"adj_close": [10, 9, 11, -1, None], "junk": [1] * 5}, index=idx)
    out = clean_prices(df)
    assert list(out.index.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]
    assert out["adj_close"].tolist() == [9, 11]  # last duplicate wins
    assert out.index.tz is None and list(out.columns) == ["adj_close"]


# --- Upload ------------------------------------------------------------------------------------

def to_csv(df, date_fmt="%Y-%m-%d", header=("Date", "Adj Close")):
    lines = [",".join(header)]
    lines += [f"{d.strftime(date_fmt)},{p:.2f}" for d, p in df["adj_close"].items()]
    return "\n".join(lines).encode()


def test_upload_iso_dates():
    h = parse_upload(to_csv(synthetic(100)), "INFY")
    assert h.source == "upload" and len(h) == 100 and h.symbol == "INFY"
    assert h.start == pd.Timestamp("2024-10-01") and not h.notes


@pytest.mark.parametrize("fmt", ["%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y"])
def test_upload_day_first_dates(fmt):
    h = parse_upload(to_csv(synthetic(100), fmt))
    assert h.start == pd.Timestamp("2024-10-01")  # 1 Oct, not 10 Jan
    assert h.end == synthetic(100).index[-1]


def test_upload_accepts_bom_commas_and_header_variants():
    text = "﻿date,adj_close\n" + "\n".join(
        f'{d:%Y-%m-%d},"1,{i:03d}.50"' for i, d in enumerate(synthetic(80).index))
    h = parse_upload(text.encode())
    assert h.adj_close.iloc[0] == 1000.5 and len(h) == 80


def test_upload_falls_back_to_close_with_a_note():
    h = parse_upload(to_csv(synthetic(100), header=("Date", "Close")))
    assert len(h) == 100 and "Close was used" in h.notes[0]


def test_upload_skips_bad_rows_with_a_note():
    rows = to_csv(synthetic(100)).decode() + "\nnot-a-date,5\n2026-01-01,abc\n"
    h = parse_upload(rows.encode())
    assert len(h) == 100 and "2 row(s)" in h.notes[0]


@pytest.mark.parametrize("content,message", [
    (b"Price\n1\n2", "No Date column"),
    (b"Date,Volume\n2026-01-01,5", "No Adj Close"),
    (to_csv(synthetic(10)), "Only 10 usable rows"),
])
def test_upload_errors_are_readable(content, message):
    with pytest.raises(UploadError, match=message):
        parse_upload(content)


# --- Fallback chain ----------------------------------------------------------------------------

def test_yahoo_is_used_when_available(monkeypatch, snapshot_dir):
    monkeypatch.setattr(data, "fetch_yahoo", lambda sym, years: synthetic())
    h = get_prices("RELIANCE", "RELIANCE.NS")
    assert h.source == "yahoo" and len(h) == 300 and not h.notes


def test_snapshot_is_used_when_yahoo_fails(monkeypatch, snapshot_dir):
    data.write_snapshot("RELIANCE", synthetic())
    h = get_prices("RELIANCE", "RELIANCE.NS")  # offline mode: Yahoo fails
    assert h.source == "snapshot" and len(h) == 300
    assert "bundled snapshot" in h.notes[0] and "offline mode" in h.notes[0]


def test_no_yahoo_and_no_snapshot_asks_for_an_upload(snapshot_dir):
    with pytest.raises(DataUnavailable, match="Upload a CSV"):
        get_prices("INFY", "INFY.NS")


def test_upload_wins_over_every_other_source(monkeypatch, snapshot_dir):
    monkeypatch.setattr(data, "fetch_yahoo", lambda sym, years: synthetic())
    h = get_prices("INFY", "INFY.NS", upload=to_csv(synthetic(90)))
    assert h.source == "upload" and len(h) == 90


def test_index_uses_the_same_chain(snapshot_dir):
    data.write_snapshot(data.NIFTY_SYMBOL, synthetic(price=25000))
    h = get_index_prices()
    assert h.source == "snapshot" and h.symbol == "^NSEI"
    assert data.snapshot_path("^NSEI").name == "NSEI.csv"


def test_snapshot_round_trip_keeps_values(snapshot_dir):
    df = synthetic()
    meta = data.write_snapshot("RELIANCE", df)
    assert meta["rows"] == 300 and meta["start"] == "2024-10-01"
    back = data.load_snapshot("RELIANCE")
    assert np.allclose(back.adj_close.values, df["adj_close"].values, atol=1e-4)
    assert back.fetched_at.tzinfo is not None


def test_short_yahoo_history_is_rejected(monkeypatch):
    monkeypatch.setenv("BMM_OFFLINE", "0")

    class FakeTicker:
        def __init__(self, sym):
            pass

        def history(self, **kw):
            return synthetic(10).rename(columns={"close": "Close", "adj_close": "Adj Close"})

    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    with pytest.raises(DataUnavailable, match="only 10 days"):
        data.fetch_yahoo("X.NS")


def test_yahoo_exceptions_become_data_unavailable(monkeypatch):
    monkeypatch.setenv("BMM_OFFLINE", "0")

    class Boom:
        def __init__(self, sym):
            raise ConnectionError("rate limited")

    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", Boom)
    with pytest.raises(DataUnavailable, match="could not be reached: ConnectionError"):
        data.fetch_yahoo("X.NS")


# --- 15-minute cache ---------------------------------------------------------------------------

def test_yahoo_results_are_cached_for_15_minutes(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cache, "_clock", lambda: clock[0])
    calls = []
    monkeypatch.setattr(data, "fetch_yahoo", lambda sym, years: calls.append(sym) or synthetic())
    get_prices("TCS", "TCS.NS")
    clock[0] = 899
    get_prices("TCS", "TCS.NS")
    assert len(calls) == 1
    clock[0] = 901
    get_prices("TCS", "TCS.NS")
    assert len(calls) == 2


def test_yahoo_failures_are_retried_after_two_minutes(monkeypatch, snapshot_dir):
    clock = [0.0]
    monkeypatch.setattr(cache, "_clock", lambda: clock[0])
    calls = []

    def failing(sym, years):
        calls.append(sym)
        raise DataUnavailable("down")

    monkeypatch.setattr(data, "fetch_yahoo", failing)
    for t in (0, 60):
        clock[0] = t
        with pytest.raises(DataUnavailable):
            get_prices("TCS", "TCS.NS")
    assert len(calls) == 1
    clock[0] = 121
    with pytest.raises(DataUnavailable):
        get_prices("TCS", "TCS.NS")
    assert len(calls) == 2
