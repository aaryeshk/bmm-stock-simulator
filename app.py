"""BMM Stock Simulator: Nifty 100 search, market dashboard and Brownian-motion price paths."""
from __future__ import annotations

import streamlit as st

from bmm.search import Status, resolve
from bmm.universe import as_of, stocks

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
                   args=(s.symbol,), use_container_width=True)

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

    market, paths, third = st.tabs(["Market now", "BMM path trace", "Dashboard 3"])
    with market:
        st.info("Price, day change, 52-week range, momentum, volatility regime, trend label and "
                "headlines arrive in Phase 4.")
    with paths:
        st.info("1,000 simulated price paths (naive bootstrap vs scientific GBM), the 5–95% cone, "
                "terminal distribution and backtest arrive in Phase 5.")
    with third:
        st.info("Coming soon.")

st.divider()
st.caption(DISCLAIMER)
