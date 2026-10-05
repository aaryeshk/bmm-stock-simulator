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
