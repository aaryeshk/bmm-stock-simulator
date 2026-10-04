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
| 2 | Data layer (Yahoo prices + headlines, cache, CSV fallback) | Done |
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

## Data

| Need | Source, in order | Notes |
|---|---|---|
| Daily prices (2 years) | Your CSV upload → Yahoo Finance → bundled snapshot | Adjusted close for all returns. Yahoo results cached 15 minutes; failures retried after 2 minutes |
| Nifty 50 (for beta) | Your CSV upload → Yahoo `^NSEI` → bundled snapshot | If none is available, beta falls back to 1.0 |
| Headlines (14 days) | Yahoo Finance + Google News RSS, merged and de-duplicated | Best effort: a failed source becomes a note, never an error |
| Market status | NSE hours 09:15–15:30 IST, holidays from `exchange_calendars` (XBOM) | Shows "unknown" past the calendar's last date (currently 31-Dec-2026) |

**Bundled snapshot.** Only Reliance and the Nifty 50 are bundled (`data/snapshots/`), to stay
within Yahoo's terms for a public repo. The [Snapshot](.github/workflows/snapshot.yml) workflow
refreshes them. Any other stock needs a live download or an upload.

**CSV upload.** A `Date` column and an `Adj Close` column (`Close` is accepted, with a warning).
Dates may be `YYYY-MM-DD` or day-first (`18/08/2026`, `18-Aug-2026`); thousands separators are
fine. At least 60 trading days, ideally 2 years.

**Tests.** `pytest` runs offline (`BMM_OFFLINE=1` is set automatically). The live path is tested
by the [Live data](.github/workflows/live-data.yml) workflow (`BMM_LIVE=1 pytest tests/test_live.py`)
on weekdays after the close and whenever the data code changes.

## Layout

```
app.py                     Streamlit entry point
bmm/universe.py            Loads the dated Nifty 100 snapshot
bmm/search.py              Query resolver (ticker, alias, name, group, prefix, fuzzy, reject)
bmm/data.py                Prices: Yahoo, snapshot fallback, CSV upload
bmm/news.py                Headlines: Yahoo Finance + Google News
bmm/market.py              NSE open/closed/holiday status in IST
bmm/cache.py               15-minute TTL cache
data/nifty100.csv          Universe snapshot
data/snapshots/            Bundled demo prices (Reliance, Nifty 50)
scripts/check_universe.py  Official-list and Yahoo check (run by CI)
scripts/make_snapshot.py   Refreshes data/snapshots (run by CI)
reference/                 Class workbook, verified sample export, Excel export spec
tests/                     Unit, headless app and live-data tests
docs/screenshots/          Headless screenshots of the app
```
