"""Live checks against Yahoo Finance and Google News. Run with BMM_LIVE=1 (CI: Live data)."""
import os

import pandas as pd
import pytest

from bmm.data import get_index_prices, get_prices
from bmm.news import get_headlines

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not os.environ.get("BMM_LIVE"), reason="set BMM_LIVE=1")]


def recent(ts, days=10):
    return ts >= pd.Timestamp.now().normalize() - pd.Timedelta(days=days)


@pytest.mark.parametrize("symbol,yahoo", [("RELIANCE", "RELIANCE.NS"), ("M&M", "M&M.NS"),
                                          ("BAJAJ-AUTO", "BAJAJ-AUTO.NS")])
def test_live_stock_pull(symbol, yahoo):
    h = get_prices(symbol, yahoo)
    assert h.source == "yahoo"
    assert len(h) > 450  # ~2 years of trading days
    assert recent(h.end)
    assert {"open", "high", "low", "close", "adj_close"} <= set(h.frame.columns)
    assert (h.adj_close > 0).all()


def test_live_nifty_pull():
    h = get_index_prices()
    assert h.source == "yahoo" and len(h) > 450 and recent(h.end)


def test_live_headlines():
    result = get_headlines("RELIANCE.NS", "Reliance Industries Ltd")
    assert result.headlines, result.notes
    assert all(recent(x.published.tz_localize(None), days=14) for x in result.headlines)


def test_live_trend_from_real_data():
    from bmm.sentiment import score_headlines
    from bmm.trend import compute_trend

    stock, index = get_prices("RELIANCE", "RELIANCE.NS"), get_index_prices()
    sentiment = score_headlines(get_headlines("RELIANCE.NS", "Reliance Industries Ltd").headlines)
    assert sentiment.count > 0 and -1 <= sentiment.score <= 1
    t = compute_trend(stock.adj_close, index.adj_close, sentiment.score)
    assert 0.05 < t.sigma < 1.0 and 0.3 < t.beta < 2.5 and abs(t.mu) <= 0.30
    print(f"RELIANCE live: {t.label} mu {t.mu:+.1%} sigma {t.sigma:.1%} beta {t.beta:.2f} "
          f"news {sentiment.score:+.2f} from {sentiment.count} headlines")
