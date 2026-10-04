import pytest

from bmm.search import Status, compact, resolve
from bmm.universe import load_universe, stocks


def symbols(stock_list):
    return {s.symbol for s in stock_list}


# --- Universe file ---------------------------------------------------------------------------

def test_universe_has_exactly_100_unique_constituents():
    df = load_universe()
    assert len(df) == 100
    assert df["symbol"].is_unique
    assert df["isin"].is_unique


def test_universe_is_dated():
    assert load_universe()["as_of"].nunique() == 1


def test_yahoo_symbols_are_nse_listings():
    for s in stocks():
        assert s.yahoo_symbol == f"{s.symbol}.NS"


def test_compact_symbols_do_not_collide():
    # The resolver ignores punctuation, so M&M and MM must not both exist, etc.
    assert len({compact(s.symbol) for s in stocks()}) == 100


def test_aliases_never_shadow_another_stocks_ticker():
    tickers = {compact(s.symbol): s.symbol for s in stocks()}
    for s in stocks():
        for a in s.aliases:
            assert tickers.get(compact(a), s.symbol) == s.symbol, (s.symbol, a)


# --- Phase 1 "done when": every ticker resolves ----------------------------------------------

@pytest.mark.parametrize("stock", stocks(), ids=lambda s: s.symbol)
def test_every_ticker_resolves_to_itself(stock):
    for query in (stock.symbol, stock.symbol.lower(), stock.yahoo_symbol):
        r = resolve(query)
        assert r.status is Status.MATCH, query
        assert r.stock.symbol == stock.symbol


@pytest.mark.parametrize("stock", stocks(), ids=lambda s: s.symbol)
def test_every_company_name_finds_its_stock(stock):
    r = resolve(stock.name)
    assert stock.symbol in symbols(r.matches), (stock.name, r)


# --- Search behaviour table ------------------------------------------------------------------

@pytest.mark.parametrize("query", ["Reliance", "RELIANCE", "reliance", "RIL", "ril",
                                   "Reliance Industries", "Reliance Industries Ltd"])
def test_reliance_loads(query):
    r = resolve(query)
    assert r.status is Status.MATCH and r.stock.symbol == "RELIANCE"


@pytest.mark.parametrize("query,expected", [
    ("HUL", "HINDUNILVR"), ("SBI", "SBIN"), ("M&M", "M&M"), ("m&m", "M&M"), ("MM", "M&M"),
    ("Mahindra", "M&M"), ("Mahindra & Mahindra", "M&M"), ("Bajaj-Auto", "BAJAJ-AUTO"),
    ("bajaj auto", "BAJAJ-AUTO"), ("L&T", "LT"), ("Airtel", "BHARTIARTL"), ("Zomato", "ETERNAL"),
    ("Infosys", "INFY"), ("LTIMindtree", "LTM"), ("Tata Steel", "TATASTEEL"), ("Vi", "IDEA"),
])
def test_aliases_and_names_load_directly(query, expected):
    r = resolve(query)
    assert r.status is Status.MATCH, r
    assert r.stock.symbol == expected


def test_tata_lists_the_whole_group_including_titan_and_trent():
    r = resolve("Tata")
    assert r.status is Status.CHOOSE
    assert {"TCS", "TATASTEEL", "TATAPOWER", "TATACONSUM", "TMPV", "TMCV",
            "TITAN", "TRENT", "TATACAP"} <= symbols(r.matches)


def test_tata_motors_is_ambiguous_after_the_demerger():
    r = resolve("Tata Motors")
    assert r.status is Status.CHOOSE
    assert symbols(r.matches) == {"TMPV", "TMCV"}


@pytest.mark.parametrize("group,members", [
    ("Adani", {"ADANIENT", "ADANIPORTS", "ADANIPOWER", "ADANIGREEN", "ADANIENSOL"}),
    ("bajaj", {"BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BAJAJHLDNG"}),
    ("HDFC", {"HDFCBANK", "HDFCLIFE", "HDFCAMC"}),
])
def test_group_queries_offer_a_pick_list(group, members):
    r = resolve(group)
    assert r.status is Status.CHOOSE
    assert members <= symbols(r.matches)


def test_partial_name_offers_candidates():
    r = resolve("Hindustan")
    assert r.status is Status.CHOOSE
    assert {"HINDUNILVR", "HAL", "HINDZINC"} <= symbols(r.matches)


@pytest.mark.parametrize("typo,expected", [("Relaince", "RELIANCE"), ("Infosis", "INFY"),
                                           ("Hindalko", "HINDALCO")])
def test_typos_get_did_you_mean(typo, expected):
    r = resolve(typo)
    assert r.status is Status.CHOOSE
    assert expected in symbols(r.matches)


# --- Phase 1 "done when": outside tickers are rejected cleanly -------------------------------

@pytest.mark.parametrize("query", ["AAPL", "TSLA", "aapl", "Apple", "Tesla", "MSFT", "NVDA",
                                   "AAPL.NS", "Berkshire Hathaway", "XYZ123", "Paytm", "Nykaa"])
def test_outside_universe_is_rejected_with_suggestions(query):
    r = resolve(query)
    assert r.status is Status.NOT_FOUND
    assert r.matches == []
    assert "not in the Nifty 100 universe for now" in r.message
    assert 1 <= len(r.suggestions) <= 5


def test_us_tech_tickers_suggest_indian_it_peers():
    for q in ("AAPL", "MSFT", "Apple"):
        assert all(s.sector == "Information Technology" for s in resolve(q).suggestions)


def test_tesla_suggests_auto_stocks():
    assert all(s.sector == "Automobile and Auto Components" for s in resolve("TSLA").suggestions)


@pytest.mark.parametrize("query", ["", "   ", None])
def test_empty_query(query):
    assert resolve(query).status is Status.EMPTY


def test_dropdown_label_format():
    reliance = resolve("RELIANCE").stock
    assert reliance.label == "Reliance Industries Ltd (RELIANCE) · Oil Gas & Consumable Fuels"


def test_pick_lists_have_no_duplicates():
    for q in ("Tata Motors", "Tata", "Adani", "Hindustan", "bank", "Power", "Relaince"):
        found = [s.symbol for s in resolve(q).matches]
        assert len(found) == len(set(found)), (q, found)


@pytest.mark.parametrize("query,sector", [("Coca Cola", "Fast Moving Consumer Goods"),
                                          ("JPM", "Financial Services"),
                                          ("Exxon", "Oil Gas & Consumable Fuels")])
def test_known_global_names_suggest_sector_peers(query, sector):
    r = resolve(query)
    assert r.status is Status.NOT_FOUND
    assert all(s.sector == sector for s in r.suggestions)


@pytest.mark.parametrize("query", ["Berkshire Hathaway", "Paytm", "XYZ123"])
def test_unrelated_names_fall_back_to_bellwethers_not_junk(query):
    assert symbols(resolve(query).suggestions) == {"RELIANCE", "HDFCBANK", "BHARTIARTL",
                                                   "TCS", "ICICIBANK"}
