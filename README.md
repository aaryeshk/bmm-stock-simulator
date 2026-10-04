# BMM Stock Simulator

Search any Nifty 100 stock, see where it stands today, and simulate its price path with a
Brownian motion model (naive bootstrap vs scientific GBM), with a class-layout Excel export.

> Educational model of stock price movement only. Not investment advice or a forecast.

## Run locally

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
streamlit run app.py
pytest -q
```

## Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Search + Nifty 100 universe | Done |
| 2 | Data layer (Yahoo prices + headlines, cache, CSV fallback) | |
| 3 | Trend engine (μ, σ) | |
| 4 | Dashboard 1: Market now | |
| 5 | Dashboard 2: BMM path trace | |
| 6 | Excel export | |
| 7 | Dashboard 3 placeholder | |
| 8 | Package + deploy | |

## Stock search

| You type | Result |
|---|---|
| `Reliance`, `RELIANCE`, `RIL`, `RELIANCE.NS` | Loads Reliance Industries |
| `Tata` | Pick list of all 9 Tata group stocks, including Titan and Trent |
| `Tata Motors` | Pick list: TMPV (passenger) or TMCV (commercial), after the 2025 demerger |
| `M&M`, `Mahindra`, `HUL`, `SBI`, `Zomato` | Loads by ticker, nickname or name |
| `Relaince`, `Infosis` | "Did you mean" pick list |
| `AAPL`, `TSLA`, `Paytm` | "Not in the Nifty 100 universe for now" + closest Nifty 100 matches (sector peers for well-known global names) |

The universe lives in [`data/nifty100.csv`](data/nifty100.csv): NSE symbol, Yahoo symbol, name,
sector, business group, aliases, ISIN and the `as_of` date it was taken from NSE. The
[Universe check](.github/workflows/universe-check.yml) workflow diffs it against NSE's official
list and checks every Yahoo symbol weekly, opening an issue when something changes (NSE
rebalances the index each March and September).

## Layout

```
app.py                     Streamlit entry point
bmm/universe.py            Loads the dated Nifty 100 snapshot
bmm/search.py              Query resolver (ticker, alias, name, group, prefix, fuzzy, reject)
data/nifty100.csv          Universe snapshot
scripts/check_universe.py  Official-list and Yahoo check (run by CI)
reference/                 Class workbook, verified sample export, Excel export spec
tests/                     Resolver, universe and headless app tests
docs/screenshots/          Headless screenshots of the app
```
