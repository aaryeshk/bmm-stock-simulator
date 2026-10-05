# Deploying the BMM Stock Simulator

The app is a single Streamlit file (`app.py`) with pinned dependencies (`requirements.txt`,
tested on Python 3.12). It needs no API keys, secrets or database.

## 1. Streamlit Community Cloud (free, public link)

1. Go to <https://share.streamlit.io> and sign in with the GitHub account that owns the repo
   (`aaryeshk`). Allow Streamlit to see `aaryeshk/bmm-stock-simulator` when asked.
2. Click **Create app** → **Deploy a public app from GitHub** and fill in:

   | Field | Value |
   |---|---|
   | Repository | `aaryeshk/bmm-stock-simulator` |
   | Branch | `main` once the work is merged; until then `claude/stock-search-dashboard-arch-3zioeg` |
   | Main file path | `app.py` |
   | App URL | e.g. `bmm-stock-simulator` → `https://bmm-stock-simulator.streamlit.app` |

3. Open **Advanced settings** and set **Python version 3.12**. Leave Secrets empty.
4. Click **Deploy**. The first build installs the requirements and takes about 3–5 minutes.
5. Paste the app URL on the second line of [`deploy/url.txt`](deploy/url.txt) and push (or
   send it to Claude). The **Smoke test** workflow then opens the live app in a headless
   browser, searches RIL, checks both dashboards and the Excel download, and uploads
   screenshots as a workflow artifact. It repeats every Monday.

Every push to the deployed branch redeploys automatically.

### Check it by hand

| Step | Expected |
|---|---|
| Type `RIL` | Reliance loads; caption **Prices: Yahoo Finance (live)** and today's NSE status |
| Market now | Price, day change, 52-week range, momentum, trend label, "Why this trend?", headlines with scores |
| BMM path trace | Cone with 1,000 paths, distribution, naive vs scientific, backtest |
| Build Excel workbook → Download .xlsx | `BMM_RELIANCE_60d_<date>.xlsx`, ~2.5 MB; opens in Excel and recalculates |
| Type `AAPL` | "Not in the Nifty 100 universe for now" with IT suggestions |

### If something is off

| Symptom | Cause and fix |
|---|---|
| Caption says **Bundled snapshot** for Reliance and other stocks ask for a CSV | Yahoo Finance is refusing requests from Streamlit Cloud's shared IP (rate limit). The app keeps working: Reliance uses the snapshot, other stocks take a CSV upload (`Date, Adj Close`). It usually clears within hours; reboot the app from the Streamlit menu to retry sooner. |
| **Headlines (0)** | Google News / Yahoo news unreachable from the host. Trend uses news score 0; set a manual score in the sidebar if needed. |
| **NSE: Market status unknown** | The holiday calendar (`exchange_calendars`) has no data for the date (it runs to 31-Dec-2026). Bump `exchange_calendars` in `requirements.txt` once a release covers 2027. |
| Build fails on a package | Check the build log in the Streamlit "Manage app" panel; make sure Python 3.12 is selected. |
| App is asleep | Free apps sleep after a few days without visitors; the first visitor wakes it (about 30 s). |

## 2. Run locally

```bash
git clone https://github.com/aaryeshk/bmm-stock-simulator && cd bmm-stock-simulator
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
streamlit run app.py          # http://localhost:8501
pytest -q                     # offline tests; Excel recalculation tests need LibreOffice Calc
```

Without internet, `BMM_OFFLINE=1 streamlit run app.py` uses the bundled Reliance snapshot.

## 3. From the zip

The zip is a `git archive` of the repository; its commit is in the zip's comment and file name. Unzip it and follow
"Run locally" from step 2, or push its contents to a new GitHub repo and deploy as in section 1.

## Keeping it healthy

| Workflow | What it watches | When |
|---|---|---|
| Tests | Lint + offline tests | Every push |
| Excel | Export recalculates in LibreOffice with 0 errors and matches the app | Changes to `bmm/`, tests, requirements |
| Live data | Real Yahoo prices and headlines | Weekdays after the close |
| Universe check | `data/nifty100.csv` vs NSE's official list; Yahoo symbols | Mondays (opens an issue on change) |
| Snapshot | Refreshes the bundled Reliance + Nifty snapshot | On demand |
| Smoke test | The deployed app, end to end | On URL change and Mondays |

Scheduled workflows only run from the default branch, so they start once the work is merged
into `main`. NSE rebalances the Nifty 100 each March and September: when the Universe check
opens an issue, update `data/nifty100.csv` (symbols, aliases, groups) and the `as_of` date.
