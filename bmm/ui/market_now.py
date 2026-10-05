"""Dashboard 1: Market now. Streamlit rendering only; the numbers come from bmm.dashboard,
bmm.trend and bmm.sentiment."""
from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from bmm.dashboard import chart_frame, day_change, momentum, range_52w
from bmm.data import PriceHistory
from bmm.market import IST, MarketStatus
from bmm.news import News
from bmm.sentiment import Sentiment
from bmm.trend import SIGMA_METHODS, Assumptions, Trend, explain

# Reference palette (dataviz skill): accent blue for the price, muted gray for context lines.
PALETTE = {
    "light": {"accent": "#2a78d6", "track": "#cde2fb", "muted": "#898781", "ink": "#0b0b0b",
              "ink2": "#52514e", "grid": "#e1e0d9"},
    "dark": {"accent": "#3987e5", "track": "#104281", "muted": "#898781", "ink": "#ffffff",
             "ink2": "#c3c2b7", "grid": "#2c2c2a"},
}
SERIES = ["Price", "50-day average", "200-day average"]
RANGES = {"6M": 126, "1Y": 255, "2Y": None}


def _mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # older Streamlit or bare-mode tests
        return "light"


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x:+.{digits}%}"


def kpi_row(prices: PriceHistory, trend: Trend | None, status: MarketStatus) -> None:
    today = datetime.now(IST).date()
    dc = day_change(prices.adj_close, status, today)
    rng = range_52w(prices.adj_close)
    c = st.columns(4)
    if dc:
        c[0].metric("Last price (₹)", f"{dc.price:,.2f}",
                    f"{dc.change:+,.2f} ({dc.pct:+.2%})", border=True,
                    help=f"{dc.label}. Previous close {dc.previous:,.2f} on "
                         f"{dc.previous_date:%d-%b-%Y}. Adjusted close.")
    if trend:
        # The delta must start with the sign: Streamlit picks the arrow from the first character.
        c[1].metric("Trend", trend.label, f"{trend.mu:+.1%} a year (μ)", border=True,
                    help=f"Bearish below −{trend.assumptions.neutral_band:.0%}, Bullish above "
                         f"+{trend.assumptions.neutral_band:.0%}. See 'Why this trend?' below.")
        t = trend.technicals
        recent = "n/a" if t.sigma_recent is None else f"{t.sigma_recent:.1%}"
        c[2].metric("Volatility σ (annual)", f"{trend.sigma:.1%}",
                    f"{t.vol_regime} · 30-day {recent}", delta_color="off", delta_arrow="off",
                    border=True,
                    help=f"{SIGMA_METHODS[trend.sigma_method]}. Regime compares 30-day with "
                         "lookback volatility: ±15% = in line.")
    c[3].metric("52-week position", f"{rng.position:.0%} of range",
                f"{rng.from_high:+.1%} from high", delta_color="off", delta_arrow="off",
                border=True,
                help="0% = at the 52-week low, 100% = at the 52-week high (adjusted closes).")
    if dc:
        st.caption(f"{dc.label} · {prices.source_label}")


def range_meter(prices: PriceHistory) -> None:
    """Same-ramp meter: light track, accent fill up to today's price, low and high labelled."""
    p = PALETTE[_mode()]
    r = range_52w(prices.adj_close)
    spot = prices.adj_close.iloc[-1]
    pos = max(0.0, min(1.0, r.position)) * 100
    st.markdown(
        f"""<div style="font:14px system-ui,-apple-system,'Segoe UI',sans-serif;color:{p['ink2']};
margin:4px 0 18px" role="img" aria-label="52-week range: low {r.low:,.2f}, high {r.high:,.2f},
today {spot:,.2f}, {r.position:.0%} of the range">
<div style="display:flex;justify-content:space-between;margin-bottom:6px">
<span><b style="color:{p['ink']}">52-week range</b></span>
<span>today {spot:,.2f} · {r.from_low:+.1%} from low · {r.from_high:+.1%} from high</span></div>
<div style="position:relative;height:10px;border-radius:5px;background:{p['track']}">
<div style="width:{pos:.1f}%;height:10px;border-radius:5px;background:{p['accent']}"></div>
<div style="position:absolute;left:calc({pos:.1f}% - 1px);top:-4px;width:2px;height:18px;
background:{p['ink']}"></div></div>
<div style="display:flex;justify-content:space-between;margin-top:6px;
font-variant-numeric:tabular-nums">
<span>Low {r.low:,.2f} ({r.low_date:%d-%b-%y})</span>
<span>High {r.high:,.2f} ({r.high_date:%d-%b-%y})</span></div></div>""",
        unsafe_allow_html=True)


def momentum_row(prices: PriceHistory, index: PriceHistory | None) -> None:
    st.markdown("**Momentum** (price return; delta = vs Nifty 50 over the same dates)")
    cols = st.columns(4)
    for col, m in zip(cols, momentum(prices.adj_close, index.adj_close if index else None),
                      strict=True):
        delta = None if m.relative is None else f"{m.relative * 100:+.1f} pts vs Nifty"
        col.metric(f"{m.window} return", _pct(m.stock), delta, border=True,
                   help=f"{m.days} trading days. Nifty 50: {_pct(m.index)}." if m.stock is not None
                   else f"Needs more than {m.days} trading days of prices.")


def price_chart(prices: PriceHistory) -> None:
    p = PALETTE[_mode()]
    left, _ = st.columns([2, 5])
    window = left.segmented_control("Chart range", list(RANGES), default="1Y", key="chart_range")
    df = chart_frame(prices.adj_close, RANGES.get(window or "1Y"))
    present = [s for s in SERIES if s in set(df["series"])]
    color = alt.Color("series:N", sort=SERIES, title=None, legend=alt.Legend(orient="top"),
                      scale=alt.Scale(domain=present,
                                      range=[p["accent"], p["muted"], p["muted"]][:len(present)]))
    dash = alt.StrokeDash("series:N", sort=SERIES, legend=None,
                          scale=alt.Scale(domain=present,
                                          range=[[1, 0], [6, 4], [2, 3]][:len(present)]))
    base = alt.Chart(df).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(grid=False, labelColor=p["muted"])),
        y=alt.Y("value:Q", title="₹ (adjusted close)", scale=alt.Scale(zero=False),
                axis=alt.Axis(gridColor=p["grid"], labelColor=p["muted"],
                              titleColor=p["ink2"], tickCount=5)))
    lines = base.mark_line(strokeWidth=2).encode(color=color, strokeDash=dash)
    last = df.sort_values("date").groupby("series").tail(1)
    labels = alt.Chart(last).mark_text(align="left", dx=6, fontSize=12, color=p["ink2"]).encode(
        x="date:T", y="value:Q", text="series:N")
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False,
                                clear="pointerout")
    wide = df.pivot(index="date", columns="series", values="value").reset_index()
    tooltip = [alt.Tooltip("date:T", title="Date", format="%d %b %Y")] + [
        alt.Tooltip(f"{s}:Q", format=",.2f") for s in present]
    rule = alt.Chart(wide).mark_rule(color=p["muted"], strokeWidth=1).encode(
        x="date:T", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=tooltip).add_params(hover)
    dot = base.transform_filter(alt.datum.series == "Price").mark_point(
        filled=True, size=70, color=p["accent"]).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    chart = (lines + labels + rule + dot).properties(height=320).configure_view(stroke=None)
    st.altair_chart(chart, width="stretch", theme="streamlit")


def why_panel(trend: Trend, sentiment: Sentiment, manual_news: float | None) -> None:
    a: Assumptions = trend.assumptions
    st.markdown("#### Trend")
    c = st.columns(4)
    c[0].metric("Final drift μ (annual)", f"{trend.mu:+.1%}")
    c[1].metric("Price-trend μ", f"{trend.price_mu:+.1%}")
    c[2].metric("News adjustment", f"{trend.news_adjustment:+.1%}",
                help=f"Score {trend.news_score:+.2f} × cap {a.news_cap:.0%}")
    c[3].metric("Beta vs Nifty 50", f"{trend.beta:.2f}", help=trend.beta_note)
    with st.expander("Why this trend?", expanded=True):
        for line in explain(trend):
            st.markdown(f"- {line}")
        rows = [{"Component": comp.label,
                 "Annual μ": "n/a" if comp.mu is None else f"{comp.mu:+.2%}",
                 "Weight": f"{comp.share:.0%}", "Contribution": f"{comp.contribution:+.2%}",
                 "How": comp.how} for comp in trend.components]
        rows += [{"Component": "Price-trend μ", "Annual μ": "", "Weight": "",
                  "Contribution": f"{trend.price_mu:+.2%}", "How": "weighted sum"},
                 {"Component": "News adjustment", "Annual μ": f"{trend.news_score:+.2f}",
                  "Weight": f"cap {a.news_cap:.0%}",
                  "Contribution": f"{trend.news_adjustment:+.2%}",
                  "How": "manual score" if manual_news is not None
                  else "no recent headlines" if sentiment.count == 0
                  else f"{sentiment.count} headlines, {sentiment.label.lower()}"},
                 {"Component": "FINAL μ", "Annual μ": "", "Weight": "",
                  "Contribution": f"{trend.mu:+.2%}",
                  "How": f"clamped to ±{a.mu_limit:.0%}" if trend.clamped else ""}]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        vols = " · ".join(f"{SIGMA_METHODS[k]} {v:.1%}" for k, v in trend.sigmas.items()
                          if v is not None)
        st.caption(f"Volatility estimates: {vols}")
        for note in trend.notes:
            st.caption(note)


def headlines(news: News, sentiment: Sentiment) -> None:
    st.markdown(f"#### Recent headlines ({sentiment.count}) · sentiment {sentiment.score:+.2f} "
                f"({sentiment.label.lower()})")
    if 0 < sentiment.count < 5:
        st.caption(f"Only {sentiment.count} headline(s), so the average {sentiment.raw_mean:+.2f} "
                   f"is scaled by {sentiment.count}/5.")
    for item in sentiment.scored:
        h = item.headline
        st.markdown(f"- `{item.score:+.2f}` [{h.title}]({h.url}) · {h.publisher} · "
                    f"{h.published.tz_convert('Asia/Kolkata'):%d %b, %H:%M} IST")
    for note in news.notes:
        st.caption(note)


def render(prices: PriceHistory, index: PriceHistory | None, trend: Trend | None,
           trend_error: str | None, status: MarketStatus, news: News, sentiment: Sentiment,
           manual_news: float | None) -> None:
    kpi_row(prices, trend, status)
    range_meter(prices)
    momentum_row(prices, index)
    price_chart(prices)
    if trend is not None:
        why_panel(trend, sentiment, manual_news)
    else:
        st.error(f"Trend not available: {trend_error}")
    headlines(news, sentiment)
