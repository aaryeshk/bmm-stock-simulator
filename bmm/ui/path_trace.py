"""Dashboard 2: BMM path trace. Streamlit rendering only; the numbers come from bmm.simulate."""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from bmm.data import PriceHistory
from bmm.excel import build_workbook, filename
from bmm.simulate import (
    HORIZON_DEFAULT,
    HORIZON_MAX,
    HORIZON_MIN,
    METHODS,
    N_PATHS,
    SEED,
    Simulation,
    backtest,
    backtest_scores,
    backtest_table,
    bands,
    simulate,
    summary,
    validation,
)
from bmm.trend import Assumptions, Trend, log_returns
from bmm.ui.market_now import _mode

# Reference palette: scientific = slot 1 (blue), naive = slot 2 (orange); bands are lighter
# steps of the blue ramp so the cone reads as one series.
COLORS = {
    "light": {"sci": "#2a78d6", "naive": "#eb6834", "outer": "#cde2fb", "inner": "#86b6ef",
              "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
              "path": "#898781"},
    "dark": {"sci": "#3987e5", "naive": "#d95926", "outer": "#104281", "inner": "#1c5cab",
             "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
             "path": "#6f6e69"},
}
SAMPLE_PATHS = 20


def controls() -> tuple[int, str, int]:
    c = st.columns([3, 2, 1])
    horizon = c[0].slider("Horizon (trading days)", HORIZON_MIN, HORIZON_MAX, HORIZON_DEFAULT,
                          5, key="sim_horizon")
    method = c[1].radio("Scientific step", METHODS, horizontal=True, key="sim_method",
                        help="Exact: S·exp((μ−σ²/2)dt + σ√dt·ε). Euler (class workbook): "
                             "S·(1 + μdt + σ√dt·ε). dt = 1/255.")
    seed = int(c[2].number_input("Seed", 0, 10**6, SEED, 1, key="sim_seed",
                                 help="Same seed = same random draws as the Excel export."))
    return horizon, method, seed


@st.cache_data(show_spinner=False, max_entries=32)
def _run(spot: float, mu: float, sigma: float, rets: tuple[float, ...], horizon: int, seed: int,
         method: str) -> Simulation:
    return simulate(spot, mu, sigma, np.array(rets), horizon, N_PATHS, seed, method)


def tiles(sim: Simulation) -> None:
    s = summary(sim)
    sci, nai = s["scientific"], s["naive"]
    c = st.columns(4)
    c[0].metric(f"Median price, day {sim.horizon} (₹)", f"{sci['median']:,.2f}",
                f"{sci['median'] / sim.spot - 1:+.1%} vs spot {sim.spot:,.2f}", border=True,
                help=f"Scientific (GBM, {sim.method}). Naive median: {nai['median']:,.2f}.")
    c[1].metric("P(ends below spot)", f"{sci['p_below']:.1%}",
                f"naive {nai['p_below']:.1%}", delta_color="off", delta_arrow="off",
                border=True, help=f"P(ends above spot): {sci['p_above']:.1%}.")
    c[2].metric("90% range (5th–95th pct)", f"{sci['p5']:,.0f} – {sci['p95']:,.0f}",
                f"{sci['low_vs_spot']:+.1%} / {sci['high_vs_spot']:+.1%} vs spot",
                delta_color="off", delta_arrow="off", border=True)
    c[3].metric("P(fall > 10%) · P(rise > 10%)",
                f"{sci['p_fall_10']:.1%} · {sci['p_rise_10']:.1%}",
                f"naive {nai['p_fall_10']:.1%} · {nai['p_rise_10']:.1%}", delta_color="off",
                delta_arrow="off", border=True)


def cone_chart(b: pd.DataFrame, sim: Simulation | None, history: pd.Series | None = None,
               realised: np.ndarray | None = None, height: int = 360) -> alt.LayerChart:
    """Percentile cone (5-95 outer, 25-75 inner), scientific median, naive median, optional
    sample paths, recent history (negative days) and a realised path (backtest)."""
    p = COLORS[_mode()]
    x = alt.X("day:Q", title="Trading days from today (0 = spot)",
              axis=alt.Axis(grid=False, labelColor=p["muted"], titleColor=p["ink2"]))
    y_axis = alt.Axis(gridColor=p["grid"], labelColor=p["muted"], titleColor=p["ink2"],
                      tickCount=6)
    y = alt.Y("value:Q", title="Price (₹)", scale=alt.Scale(zero=False), axis=y_axis)
    layers = [
        alt.Chart(b).mark_area(color=p["outer"], opacity=0.9).encode(
            x=x, y=alt.Y("p5:Q", title="Price (₹)", scale=alt.Scale(zero=False), axis=y_axis),
            y2="p95:Q"),
        alt.Chart(b).mark_area(color=p["inner"], opacity=0.9).encode(x=x, y="p25:Q", y2="p75:Q"),
    ]
    if sim is not None:
        n = min(SAMPLE_PATHS, sim.paths.shape[1])
        sp = pd.DataFrame(sim.paths[:, :n]).reset_index(names="day").melt(
            "day", var_name="path", value_name="value")
        layers.append(alt.Chart(sp).mark_line(strokeWidth=0.8, opacity=0.45,
                                              color=p["path"]).encode(x=x, y=y, detail="path:N"))
    lines = [b[["day"]].assign(series="Scientific median", value=b["p50"]),
             b[["day"]].assign(series="Naive median", value=b["naive_median"])]
    domain = ["Scientific median", "Naive median"]
    rng, dash = [p["sci"], p["naive"]], [[1, 0], [6, 4]]
    if history is not None and len(history):
        h = pd.DataFrame({"day": np.arange(-len(history) + 1, 1), "value": history.to_numpy(),
                          "series": "Actual (history)"})
        lines.append(h)
        domain.append("Actual (history)")
        rng.append(p["ink"])
        dash.append([1, 0])
    if realised is not None:
        lines.append(pd.DataFrame({"day": np.arange(len(realised)), "value": realised,
                                   "series": "Actual (what happened)"}))
        domain.append("Actual (what happened)")
        rng.append(p["ink"])
        dash.append([1, 0])
    long = pd.concat(lines, ignore_index=True)
    layers.append(alt.Chart(long).mark_line(strokeWidth=2).encode(
        x=x, y=y,
        color=alt.Color("series:N", title=None, scale=alt.Scale(domain=domain, range=rng),
                        legend=alt.Legend(orient="top")),
        strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=domain, range=dash),
                                  legend=None)))
    hover = alt.selection_point(fields=["day"], nearest=True, on="pointerover", empty=False,
                                clear="pointerout")
    tip = [alt.Tooltip("day:Q", title="Day")] + [
        alt.Tooltip(f"{c}:Q", title=t, format=",.2f")
        for c, t in (("p95", "95th pct"), ("p75", "75th pct"), ("p50", "Median"),
                     ("p25", "25th pct"), ("p5", "5th pct"), ("naive_median", "Naive median"))]
    layers.append(alt.Chart(b).mark_rule(color=p["muted"]).encode(
        x="day:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=tip).add_params(hover))
    return alt.layer(*layers).properties(height=height).configure_view(stroke=None)


def distribution_chart(sim: Simulation) -> alt.Chart:
    """Terminal price distribution, scientific vs naive, as frequency polygons on shared bins."""
    p = COLORS[_mode()]
    both = np.r_[sim.paths[-1], sim.naive[-1]]
    edges = np.linspace(both.min(), both.max(), 41)
    mids = (edges[:-1] + edges[1:]) / 2
    rows = []
    for name, term in (("Scientific (GBM)", sim.paths[-1]), ("Naive bootstrap", sim.naive[-1])):
        counts, _ = np.histogram(term, edges)
        rows.append(pd.DataFrame({"price": mids, "paths": counts, "series": name}))
    df = pd.concat(rows, ignore_index=True)
    domain = ["Scientific (GBM)", "Naive bootstrap"]
    lines = alt.Chart(df).mark_line(strokeWidth=2, interpolate="step").encode(
        x=alt.X("price:Q", title=f"Price on day {sim.horizon} (₹)",
                axis=alt.Axis(grid=False, labelColor=p["muted"], titleColor=p["ink2"])),
        y=alt.Y("paths:Q", title="Paths",
                axis=alt.Axis(gridColor=p["grid"], labelColor=p["muted"], titleColor=p["ink2"])),
        color=alt.Color("series:N", title=None, legend=alt.Legend(orient="top"),
                        scale=alt.Scale(domain=domain, range=[p["sci"], p["naive"]])),
        tooltip=[alt.Tooltip("series:N", title="Method"),
                 alt.Tooltip("price:Q", title="Price ≈", format=",.0f"),
                 alt.Tooltip("paths:Q", title="Paths")])
    spot = alt.Chart(pd.DataFrame({"x": [sim.spot], "y": [df["paths"].max()],
                                   "label": [f"spot {sim.spot:,.0f}"]}))
    rule = spot.mark_rule(color=p["ink2"], strokeDash=[2, 2]).encode(x="x:Q")
    text = spot.mark_text(align="left", dx=4, dy=4, baseline="top", color=p["ink2"],
                          fontSize=12).encode(x="x:Q", y="y:Q", text="label:N")
    return (lines + rule + text).properties(height=260).configure_view(stroke=None)


def comparison_table(sim: Simulation) -> pd.DataFrame:
    s = summary(sim)
    rows = [("Mean price", "mean", "₹"), ("Median price", "median", "₹"),
            ("5th percentile", "p5", "₹"), ("95th percentile", "p95", "₹"),
            ("Expected return (mean / spot − 1)", "expected_return", "%"),
            ("P(price ends below spot)", "p_below", "%"),
            ("P(fall more than 10%)", "p_fall_10", "%"),
            ("P(rise more than 10%)", "p_rise_10", "%")]

    def fmt(v: float, kind: str) -> str:
        return f"{v:,.2f}" if kind == "₹" else f"{v:.1%}"

    return pd.DataFrame([{"Outcome at horizon": label,
                          "Scientific": fmt(s["scientific"][k], kind),
                          "Naive": fmt(s["naive"][k], kind)} for label, k, kind in rows])


def validation_table(sim: Simulation) -> pd.DataFrame:
    v = validation(sim)
    fmt = [",.2f", ",.2f", ".1%", ".4f", ".4f"]
    return pd.DataFrame({"Quantity": v["Quantity"],
                         "Theory": [format(x, f) for x, f in zip(v["Theory"], fmt, strict=True)],
                         "Simulated": [format(x, f) for x, f in zip(v["Simulated"], fmt,
                                                                     strict=True)],
                         "Gap": [f"{g:+.1%}" for g in v["Gap"]]})


@st.cache_data(show_spinner="Running the backtest…", max_entries=16)
def _backtest(prices: pd.Series, index: pd.Series | None, horizon: int,
              assumptions: Assumptions, method: str, seed: int):
    return backtest(prices, index, horizon, assumptions, method, seed)


def backtest_section(prices: PriceHistory, index: PriceHistory | None, horizon: int,
                     assumptions: Assumptions, method: str, seed: int) -> None:
    st.markdown("#### Backtest: would the cone have held?")
    st.caption("Each window re-estimates μ and σ using only prices up to its start date "
               "(price trend only: past headlines are not available), simulates "
               f"{horizon} days ahead and compares with what actually happened. Windows start "
               "every 20 trading days after the first year of data.")
    windows = _backtest(prices.adj_close, index.adj_close if index else None, horizon,
                        assumptions, method, seed)
    if not windows:
        st.info(f"Needs at least {255 + horizon + 1} trading days of prices "
                f"({len(prices)} available). Try a shorter horizon.")
        return
    sc = backtest_scores(windows)
    sci, nai = sc["scientific"], sc["naive"]
    c = st.columns(3)
    c[0].metric("Actual end price inside the 5–95% range", f"{sci['inside_rate']:.0%}",
                f"naive {nai['inside_rate']:.0%} · target 90%", delta_color="off",
                delta_arrow="off", border=True, help=f"{sci['windows']} windows (overlapping).")
    c[1].metric("Days the actual path stayed inside the band", f"{sci['days_inside']:.0%}",
                f"naive {nai['days_inside']:.0%}", delta_color="off", delta_arrow="off",
                border=True)
    c[2].metric("Direction right (median vs spot)", f"{sci['direction_rate']:.0%}",
                f"naive {nai['direction_rate']:.0%}", delta_color="off", delta_arrow="off",
                border=True, help="Median above spot and the price rose, or below and fell.")
    last = windows[-1]
    st.markdown(f"**Most recent window:** {last.start:%d-%b-%Y} → {last.end:%d-%b-%Y} · "
                f"μ {last.mu:+.1%}, σ {last.sigma:.1%} · actual {last.realised[-1]:,.2f} vs "
                f"spot {last.spot:,.2f}, landing at the {last.sci_rank:.0%} percentile of the "
                f"scientific paths ({last.naive_rank:.0%} of the naive).")
    st.altair_chart(cone_chart(last.bands, None, realised=last.realised, height=300),
                    width="stretch", theme="streamlit")
    table = backtest_table(windows)
    for col in ("Spot", "Actual end"):
        table[col] = table[col].map("{:,.2f}".format)
    for col in ("μ used", "σ used"):
        table[col] = table[col].map("{:+.1%}".format if col == "μ used" else "{:.1%}".format)
    with st.expander(f"All {len(windows)} windows"):
        st.dataframe(table, hide_index=True, width="stretch")


def excel_section(ticker: str, company: str, prices: PriceHistory,
                  index: PriceHistory | None, trend: Trend, sim: Simulation,
                  news_note: str) -> None:
    st.markdown("#### Excel export (class-workbook layout)")
    st.caption("Inputs, Prices, Shocks, Paths, NaiveDraws, Naive, Bands, RandDemo and Summary "
               "sheets. The shocks and naive draws are this run's, stored as values, so the "
               "workbook shows these exact paths; every other cell is a live formula.")
    key = (ticker, len(prices), str(prices.end), sim.horizon, sim.method, sim.seed,
           round(trend.mu, 12), round(trend.sigma, 12), trend.sigma_method)
    if st.button("Build Excel workbook", key="xl_build"):
        with st.spinner("Writing about 130,000 formulas…"):
            data_note = (f"{prices.source_label}: adjusted closes {prices.start:%d-%b-%Y} to "
                         f"{prices.end:%d-%b-%Y} ({len(prices)} days)."
                         + (f" Nifty 50: {index.source_label}." if index else
                            " Nifty 50 unavailable: beta set to 1.0."))
            st.session_state["xl"] = (key, build_workbook(
                ticker=ticker, company=company, prices=prices.adj_close,
                index=index.adj_close if index else None, trend=trend, sim=sim,
                news_note=news_note, data_note=data_note))
    held = st.session_state.get("xl")
    if held and held[0] == key:
        st.download_button("Download .xlsx", held[1], filename(ticker, sim.horizon, prices.end),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="xl_download", type="primary")
    elif held:
        st.caption("Inputs have changed since the workbook was built. Build it again to export "
                   "the current run.")


def render(prices: PriceHistory, index: PriceHistory | None, trend: Trend,
           assumptions: Assumptions, ticker: str = "", company: str = "",
           news_note: str = "") -> Simulation:
    horizon, method, seed = controls()
    rets = log_returns(prices.adj_close)
    sim = _run(trend.spot, trend.mu, trend.sigma, tuple(rets), horizon, seed, method)
    st.caption(f"{N_PATHS:,} paths · μ {trend.mu:+.1%} ({trend.label.lower()}) · "
               f"σ {trend.sigma:.1%} · dt = 1/255 · {method} step · seed {seed} · naive draws from "
               f"{len(rets)} historical daily returns")
    tiles(sim)
    b = bands(sim)
    st.markdown("#### Path trace: 5–95% and 25–75% cone")
    st.altair_chart(cone_chart(b, sim, prices.adj_close.iloc[-40:]), width="stretch",
                    theme="streamlit")
    st.caption(f"Shaded: 5–95% (light) and 25–75% (darker) of the scientific paths. Grey: "
               f"{SAMPLE_PATHS} sample paths. Naive median dashed. Paths tilt with μ: "
               f"theory median {sim.spot * np.exp((sim.mu - sim.sigma**2 / 2) * sim.T):,.2f}.")
    left, right = st.columns([1, 1])
    with left:
        st.markdown(f"#### Price on day {horizon}")
        st.altair_chart(distribution_chart(sim), width="stretch", theme="streamlit")
    with right:
        st.markdown("#### Naive vs scientific")
        st.dataframe(comparison_table(sim), hide_index=True, width="stretch")
        st.caption("The naive bootstrap replays historical daily returns, so it carries the "
                   "lookback's own drift, not the trend inputs.")
    with st.expander("Validation vs closed-form theory"):
        st.dataframe(validation_table(sim), hide_index=True, width="stretch")
        st.caption("Gaps of a few percent are sampling noise from 1,000 paths. Theory assumes "
                   "the Exact step; Euler shifts it slightly.")
    excel_section(ticker, company or ticker, prices, index, trend, sim, news_note)
    backtest_section(prices, index, horizon, assumptions, method, seed)
    return sim
