"""Headless runs of the Streamlit app."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def app():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def search(at, text):
    at.text_input(key="query").set_value(text).run()
    assert not at.exception
    return at


def test_starts_empty(app):
    assert "symbol" not in app.session_state
    assert any("Search or browse" in m.value for m in app.markdown)


def test_alias_loads_stock(app):
    search(app, "RIL")
    assert app.session_state["symbol"] == "RELIANCE"
    assert app.subheader[0].value == "Reliance Industries Ltd (RELIANCE)"
    assert [t.label for t in app.tabs] == ["Market now", "BMM path trace", "Dashboard 3"]


def test_group_shows_pick_list_and_picking_loads(app):
    search(app, "Tata")
    picker = app.selectbox(key="choose::Tata")
    shown = " ".join(picker.options)
    assert all(f"({sym})" in shown for sym in ("TCS", "TITAN", "TRENT", "TMPV", "TMCV"))
    picker.set_value("TITAN").run()
    assert app.session_state["symbol"] == "TITAN"


def test_outside_ticker_is_rejected_with_suggestions(app):
    search(app, "AAPL")
    assert "not in the Nifty 100 universe for now" in app.warning[0].value
    assert "symbol" not in app.session_state
    app.button(key="suggest::INFY").click().run()
    assert app.session_state["symbol"] == "INFY"


def test_browse_lists_all_100(app):
    browse = app.selectbox(key="browse")
    assert len(browse.options) == 100
    assert "Mahindra & Mahindra Ltd (M&M) · Automobile and Auto Components" in browse.options
    browse.set_value("M&M").run()
    assert app.session_state["symbol"] == "M&M"


def test_demo_stock_falls_back_to_the_bundled_snapshot(app):
    search(app, "RELIANCE")  # tests run offline, so Yahoo is unavailable
    assert any("bundled snapshot" in i.value for i in app.info)
    assert any("Bundled snapshot" in c.value and "500 trading days" in c.value
               for c in app.caption)
    assert any(c.value.startswith("**Nifty 50:** Bundled snapshot") for c in app.caption)
    assert not app.error


def test_other_stocks_ask_for_an_upload_when_offline(app):
    search(app, "INFY")
    assert "Upload a CSV instead" in app.error[0].value
    assert app.expander[0].label == "Use your own CSV"


def test_market_status_is_shown(app):
    search(app, "TCS")
    assert any("NSE:" in c.value for c in app.caption)


def snapshot_trend(**changes):
    from bmm.data import load_snapshot
    from bmm.trend import Assumptions, compute_trend

    stock, index = load_snapshot("RELIANCE"), load_snapshot("^NSEI")
    news = changes.pop("news_score", 0.0)  # offline: no headlines, so automatic score is 0
    return compute_trend(stock.adj_close, index.adj_close, news, Assumptions().with_(**changes))


def metrics(app):
    return {m.label: m.value for m in app.metric}


def test_trend_panel_shows_the_engine_numbers(app):
    search(app, "RIL")
    t = snapshot_trend()
    m = metrics(app)
    assert m["Trend"] == t.label
    assert m["Final drift μ (annual)"] == f"{t.mu:+.1%}"
    assert m["Volatility σ (annual)"] == f"{t.sigma:.1%}"
    assert m["Beta vs Nifty 50"] == f"{t.beta:.2f}"
    why = " ".join(md.value for md in app.markdown)
    assert f"final drift μ = {t.mu:+.1%}" in why


def test_manual_news_score_moves_mu_by_score_times_cap(app):
    search(app, "RIL")
    app.radio(key="a::news_mode").set_value("Manual").run()
    app.slider(key="a::news_manual").set_value(-0.5).run()
    t = snapshot_trend(news_score=-0.5)
    assert metrics(app)["Final drift μ (annual)"] == f"{t.mu:+.1%}"
    assert t.news_adjustment == -0.05


def test_switching_sigma_method_updates_sigma(app):
    search(app, "RIL")
    app.radio(key="a::sigma").set_value("ewma").run()
    t = snapshot_trend(sigma_method="ewma")
    assert metrics(app)["Volatility σ (annual)"] == f"{t.sigma:.1%}"


def test_changing_risk_free_rate_changes_capm(app):
    search(app, "RIL")
    app.number_input(key="a::risk_free").set_value(8.0).run()
    t = snapshot_trend(risk_free=0.08)
    assert metrics(app)["Final drift μ (annual)"] == f"{t.mu:+.1%}"
    table = app.dataframe[0].value
    capm = table.loc[table["Component"] == "CAPM expected return", "How"].iloc[0]
    assert capm.startswith("r 8.00%")


# --- Dashboard 1: Market now ---------------------------------------------------------------------

def test_market_now_tiles_match_the_numbers(app):
    from bmm.dashboard import momentum, range_52w
    from bmm.data import load_snapshot

    search(app, "RIL")
    s, i = load_snapshot("RELIANCE").adj_close, load_snapshot("^NSEI").adj_close
    m = metrics(app)
    assert m["Last price (₹)"] == f"{s.iloc[-1]:,.2f}"
    assert m["Trend"] == snapshot_trend().label
    assert m["52-week position"] == f"{range_52w(s).position:.0%} of range"
    for mo in momentum(s, i):
        assert m[f"{mo.window} return"] == f"{mo.stock:+.1%}"
    deltas = {x.label: x.delta for x in app.metric}
    one_month = next(mo for mo in momentum(s, i) if mo.window == "1M")
    assert deltas["1M return"] == f"{one_month.relative * 100:+.1f} pts vs Nifty"
    assert any("52-week range" in md.value for md in app.markdown)
    assert app.get("vega_lite_chart"), "price chart missing"


def test_chart_range_control_switches_window(app):
    search(app, "RIL")
    for window in ("6M", "2Y", "1Y"):
        app.segmented_control(key="chart_range").set_value(window).run()
        assert not app.exception


def test_short_history_still_renders(app, monkeypatch):
    import numpy as np
    import pandas as pd

    from bmm import data

    idx = pd.bdate_range("2026-05-01", periods=100)
    frame = pd.DataFrame({"adj_close": 100 * np.exp(np.linspace(0, 0.1, 100))}, index=idx)
    fake = data.PriceHistory("INFY", frame, "upload", pd.Timestamp.now(tz="UTC"))
    monkeypatch.setattr(data, "get_prices", lambda *a, **k: fake)
    search(app, "INFY")
    m = metrics(app)
    assert m["1M return"] != "n/a" and m["6M return"] == "n/a" and m["1Y return"] == "n/a"
    assert m["Trend"] in {"Bearish", "Neutral", "Bullish"}


def test_trend_delta_starts_with_its_sign(app):
    # Streamlit colours the delta arrow from its first character: "μ -15%" showed a green arrow.
    search(app, "RIL")
    delta = {x.label: x.delta for x in app.metric}["Trend"]
    assert delta[0] in "+-" and delta.endswith("a year (μ)")


# --- Dashboard 2: BMM path trace ------------------------------------------------------------------

def snapshot_sim(horizon=60, method="Exact", seed=42):
    from bmm.data import load_snapshot
    from bmm.simulate import simulate, summary
    from bmm.trend import log_returns

    t = snapshot_trend()
    rets = log_returns(load_snapshot("RELIANCE").adj_close).to_numpy()
    return summary(simulate(t.spot, t.mu, t.sigma, rets, horizon, 1000, seed, method))


def test_path_trace_tiles_match_a_direct_simulation(app):
    search(app, "RIL")
    s = snapshot_sim()["scientific"]
    m = metrics(app)
    assert m["Median price, day 60 (₹)"] == f"{s['median']:,.2f}"
    assert m["P(ends below spot)"] == f"{s['p_below']:.1%}"
    assert m["90% range (5th–95th pct)"] == f"{s['p5']:,.0f} – {s['p95']:,.0f}"
    assert "Actual end price inside the 5–95% range" in m   # backtest ran
    tables = [d.value for d in app.dataframe]
    comparison = next(t for t in tables if "Outcome at horizon" in t.columns)
    assert comparison.iloc[1]["Scientific"] == f"{s['median']:,.2f}"


def test_horizon_method_and_seed_controls(app):
    search(app, "RIL")
    app.slider(key="sim_horizon").set_value(120).run()
    exact = snapshot_sim(120)["scientific"]
    assert metrics(app)["Median price, day 120 (₹)"] == f"{exact['median']:,.2f}"
    app.radio(key="sim_method").set_value("Euler").run()
    euler = snapshot_sim(120, "Euler")["scientific"]
    assert metrics(app)["Median price, day 120 (₹)"] == f"{euler['median']:,.2f}"
    app.number_input(key="sim_seed").set_value(7).run()
    seeded = snapshot_sim(120, "Euler", 7)["scientific"]
    assert metrics(app)["P(ends below spot)"] == f"{seeded['p_below']:.1%}"
    assert not app.exception


def test_excel_export_builds_and_offers_a_download(app):
    import io

    from openpyxl import load_workbook

    search(app, "RIL")
    assert not app.get("download_button")
    app.button(key="xl_build").click().run()
    assert not app.exception
    data = app.session_state["xl"][1]
    wb = load_workbook(io.BytesIO(data))
    assert wb["Inputs"]["B4"].value == "RELIANCE" and wb["Inputs"]["B10"].value == 60
    assert "No recent headlines" in wb["ReadMe"]["B11"].value
    assert app.get("download_button")
    app.slider(key="sim_horizon").set_value(90).run()      # stale after a change
    assert not app.get("download_button")
    assert any("Build it again" in c.value for c in app.caption)
