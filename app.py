"""BMM Stock Simulator: Nifty 100 search, market dashboard and Brownian-motion price paths."""
from __future__ import annotations

import streamlit as st

from bmm.data import (
    UPLOAD_HELP,
    DataUnavailable,
    PriceHistory,
    UploadError,
    get_index_prices,
    get_prices,
)
from bmm.market import MarketStatus, is_stale, market_status
from bmm.news import get_headlines
from bmm.search import Status, resolve
from bmm.sentiment import score_headlines
from bmm.trend import (
    COMPONENT_LABELS,
    COMPONENTS,
    SIGMA_METHODS,
    Assumptions,
    compute_trend,
)
from bmm.ui import market_now, path_trace
from bmm.universe import Stock, as_of, stocks

DISCLAIMER = (
    "Educational model of stock price movement only. Not investment advice or a forecast. "
    "Brownian motion assumes constant drift and volatility and normally distributed log returns, "
    "which real markets do not follow."
)

st.set_page_config(page_title="BMM Stock Simulator", page_icon="📈", layout="wide")

BY_SYMBOL = {s.symbol: s for s in stocks()}
LABELS = {s.symbol: s.label for s in stocks()}


def pick(symbol: str) -> None:
    st.session_state.symbol = symbol


def on_search() -> None:
    result = resolve(st.session_state.query)
    if result.status is Status.MATCH:
        pick(result.stock.symbol)


def on_choose(key: str) -> None:
    if st.session_state[key]:
        pick(st.session_state[key])


def uploaded(key: str) -> bytes | None:
    file = st.session_state.get(key)
    return file.getvalue() if file is not None else None


def load(symbol: str, loader) -> tuple[PriceHistory | None, str | None]:
    try:
        return loader(), None
    except (DataUnavailable, UploadError) as exc:
        return None, str(exc)


def describe(h: PriceHistory) -> str:
    return (f"{h.source_label} · {len(h)} trading days, {h.start:%d-%b-%Y} to {h.end:%d-%b-%Y}"
            f" · last adjusted close {h.adj_close.iloc[-1]:,.2f}")


def show_data(stock: Stock, status: MarketStatus) -> tuple[PriceHistory | None,
                                                          PriceHistory | None]:
    """Status line, price and index sources, and the CSV upload. Returns (stock, index)."""
    icon = {"open": "🟢", "closed": "🔴", "unknown": "⚪"}[status.state]
    st.caption(f"{icon} NSE: {status.label}. {status.detail}")

    stock_key, index_key = f"upload::{stock.symbol}", "upload::^NSEI"
    prices, error = load(stock.symbol, lambda: get_prices(
        stock.symbol, stock.yahoo_symbol, uploaded(stock_key)))
    index, index_error = load("^NSEI", lambda: get_index_prices(uploaded(index_key)))

    with st.expander("Use your own CSV", expanded=prices is None):
        st.caption(UPLOAD_HELP)
        st.file_uploader(f"{stock.symbol} daily prices", type="csv", key=stock_key)
        st.file_uploader("Nifty 50 daily prices (optional, used for beta)", type="csv",
                         key=index_key)

    if prices is None:
        st.error(error)
        return None, index
    st.caption(f"**Prices:** {describe(prices)}")
    for note in prices.notes:
        st.info(note)
    if prices.source != "upload" and is_stale(prices.end.date(), status):
        st.warning(f"Prices end on {prices.end:%d-%b-%Y}, before the last NSE close "
                   f"({status.last_close:%d-%b-%Y}).")
    if index is not None:
        st.caption(f"**Nifty 50:** {describe(index)}")
    else:
        st.warning(f"Nifty 50 data unavailable, so beta will fall back to 1.0. {index_error}")
    return prices, index


DEFAULTS = Assumptions()
PCT_INPUTS = {  # key: (label, default, min, max, step, help)
    "risk_free": ("Risk-free rate r (%)", DEFAULTS.risk_free, 0.0, 15.0, 0.01,
                  "91-day T-bill cut-off yield (RBI). Tenor matched to a ~60-day horizon."),
    "erp": ("Equity risk premium (%)", DEFAULTS.erp, 0.0, 15.0, 0.25, "Assumption for India."),
    "news_cap": ("News adjustment cap (%/yr)", DEFAULTS.news_cap, 0.0, 30.0, 1.0,
                 "Drift change when the news score is ±1."),
    "mu_limit": ("Drift limit ±(%/yr)", DEFAULTS.mu_limit, 5.0, 100.0, 5.0,
                 "Final μ is clamped to this range."),
    "neutral_band": ("Neutral band ±(%/yr)", DEFAULTS.neutral_band, 0.0, 20.0, 0.5,
                     "|μ| within this band is labelled Neutral."),
}


def reset_assumptions() -> None:
    for k in [k for k in st.session_state if str(k).startswith("a::")]:
        del st.session_state[k]


def sidebar_assumptions() -> tuple[Assumptions, float | None]:
    """Assumption controls. Returns the assumptions and a manual news score (None = automatic)."""
    with st.sidebar:
        st.header("Assumptions")
        method = st.radio("Volatility σ", list(SIGMA_METHODS), format_func=SIGMA_METHODS.get,
                          key="a::sigma", help="Lookback matches the class workbook "
                          "(STDEV of daily log returns × √255).")
        values = {k: st.number_input(label, min_value=lo, max_value=hi, step=step,
                                     value=round(default * 100, 4), key=f"a::{k}", help=help_) / 100
                  for k, (label, default, lo, hi, step, help_) in PCT_INPUTS.items()}
        st.subheader("Drift weights")
        weights = {k: st.slider(COMPONENT_LABELS[k], 0.0, 1.0, DEFAULTS.weights[k], 0.05,
                                key=f"a::w::{k}") for k in COMPONENTS}
        st.subheader("News")
        mode = st.radio("News score", ["From headlines", "Manual"], key="a::news_mode",
                        horizontal=True)
        manual = (st.slider("Manual score", -1.0, 1.0, 0.0, 0.05, key="a::news_manual",
                            help="-1 very bearish, +1 very bullish. 0 = price-only trend.")
                  if mode == "Manual" else None)
        st.button("Reset to defaults", on_click=reset_assumptions)
    if sum(weights.values()) <= 0:
        st.sidebar.error("All weights are zero; using the defaults.")
        weights = DEFAULTS.weights
    return DEFAULTS.with_(sigma_method=method, weights=weights, **values), manual


st.title("BMM Stock Simulator")
st.caption(f"Nifty 100 universe as of {as_of()} · stock price movement only")

search_col, browse_col = st.columns([3, 2])
with search_col:
    query = st.text_input("Search a Nifty 100 stock", key="query", on_change=on_search,
                          placeholder="Reliance, RIL, Tata, M&M, HUL…")
with browse_col:
    st.selectbox("Or browse all 100", options=list(LABELS), format_func=LABELS.get, index=None,
                 key="browse", on_change=on_choose, args=("browse",),
                 placeholder="Type to filter by name, ticker or sector")

result = resolve(query)
if result.status is Status.CHOOSE:
    st.info(result.message)
    key = f"choose::{result.query}"
    st.selectbox("Matches", options=[s.symbol for s in result.matches], format_func=LABELS.get,
                 index=None, key=key, on_change=on_choose, args=(key,),
                 placeholder="Pick a stock", label_visibility="collapsed")
elif result.status is Status.NOT_FOUND:
    st.warning(result.message)
    st.write("Closest Nifty 100 matches:")
    cols = st.columns(len(result.suggestions))
    for col, s in zip(cols, result.suggestions, strict=True):
        col.button(f"{s.name} ({s.symbol})", key=f"suggest::{s.symbol}", on_click=pick,
                   args=(s.symbol,), width="stretch")

stock = BY_SYMBOL.get(st.session_state.get("symbol"))
st.divider()
if stock is None:
    st.write("Search or browse to load a stock.")
else:
    st.subheader(f"{stock.name} ({stock.symbol})")
    details = [stock.sector, f"Yahoo: {stock.yahoo_symbol}"]
    if stock.group:
        details.insert(1, f"{stock.group} group")
    st.caption(" · ".join(details))

    assumptions, manual_news = sidebar_assumptions()
    status = market_status()
    prices, index = show_data(stock, status)
    news = get_headlines(stock.yahoo_symbol, stock.name)
    sentiment = score_headlines(news.headlines)
    trend, trend_error = None, None
    if prices is not None:
        try:
            trend = compute_trend(prices.adj_close, index.adj_close if index else None,
                                  sentiment.score if manual_news is None else manual_news,
                                  assumptions)
        except ValueError as exc:
            trend_error = str(exc)

    market, paths, third = st.tabs(["Market now", "BMM path trace", "Dashboard 3"])
    with market:
        if prices is None:
            st.info("Load prices (live, snapshot or your CSV) to see the dashboard.")
            market_now.headlines(news, sentiment)
        else:
            market_now.render(prices, index, trend, trend_error, status, news, sentiment,
                              manual_news)
    with paths:
        if trend is None:
            st.info("Load prices to simulate paths." if prices is None
                    else f"Trend not available: {trend_error}")
        else:
            news_note = (f"Manual score {manual_news:+.2f}." if manual_news is not None else
                         f"Score {sentiment.score:+.2f} from {sentiment.count} headlines of the "
                         "last 14 days (VADER + Loughran-McDonald + market-move words)."
                         if sentiment.count else "No recent headlines: score 0.")
            path_trace.render(prices, index, trend, assumptions, stock.symbol, stock.name,
                              news_note)
    with third:
        st.info("Coming soon.")

st.divider()
st.caption(DISCLAIMER)
