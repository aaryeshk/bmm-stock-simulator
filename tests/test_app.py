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
