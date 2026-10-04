"""Check data/nifty100.csv against NSE's official Nifty 100 list and against Yahoo Finance.

Runs in GitHub Actions (weekly, manual, and whenever the universe file changes), because NSE and
Yahoo are not reachable from every environment. Exit code 1 means something needs fixing; the
Markdown report written by --report says what.

    python scripts/check_universe.py --official --yahoo --report report.md
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bmm.universe import UNIVERSE_CSV, load_universe  # noqa: E402

OFFICIAL_URLS = [
    "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36",
    "Accept": "text/csv,*/*",
}


def fetch_official() -> pd.DataFrame:
    errors = []
    for url in OFFICIAL_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip() for c in df.columns]
            if "Symbol" in df.columns and len(df) >= 90:
                return df
            errors.append(f"{url}: unexpected content ({len(df)} rows, columns {list(df.columns)})")
        except Exception as exc:  # network errors, HTTP errors, parse errors
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Could not fetch the official Nifty 100 list:\n" + "\n".join(errors))


def check_official(universe: pd.DataFrame | None, lines: list[str]) -> bool:
    official = fetch_official()
    lines.append(f"## Official list\n\nFetched {len(official)} constituents.\n")
    if universe is None:
        return False
    ours, theirs = set(universe["symbol"]), set(official["Symbol"].str.strip())
    missing, extra = sorted(theirs - ours), sorted(ours - theirs)
    if missing:
        rows = official[official["Symbol"].isin(missing)]
        lines.append("**In the official list but not in nifty100.csv:**\n")
        lines += [f"- `{r.Symbol}` {r['Company Name']} ({r.Industry})" for _, r in rows.iterrows()]
        lines.append("")
    if extra:
        lines.append("**In nifty100.csv but no longer in the official list:**\n")
        lines += [f"- `{s}`" for s in extra]
        lines.append("")
    if not missing and not extra:
        lines.append("nifty100.csv matches the official list.\n")
    return not missing and not extra


def check_yahoo(universe: pd.DataFrame, lines: list[str]) -> bool:
    import yfinance as yf

    symbols = list(universe["yahoo_symbol"])
    data = yf.download(symbols, period="5d", group_by="ticker", progress=False, threads=True,
                       auto_adjust=False)
    dead = []
    for sym in symbols:
        try:
            close = data[sym]["Close"].dropna()
        except KeyError:
            close = pd.Series(dtype=float)
        if close.empty:
            dead.append(sym)
    lines.append(f"## Yahoo Finance\n\nChecked {len(symbols)} symbols.\n")
    if dead:
        lines.append("**No recent prices for:**\n")
        lines += [f"- `{s}`" for s in dead]
        lines.append("")
    else:
        lines.append("Every symbol returned recent prices.\n")
    return not dead


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--official", action="store_true", help="diff against NSE's official list")
    p.add_argument("--yahoo", action="store_true", help="check every Yahoo symbol has prices")
    p.add_argument("--print-official", action="store_true", help="print the official CSV")
    p.add_argument("--report", type=Path, help="write a Markdown report here")
    args = p.parse_args()

    if args.print_official:
        print(fetch_official().to_csv(index=False))

    universe = load_universe() if UNIVERSE_CSV.exists() else None
    lines = ["# Nifty 100 universe check\n"]
    if universe is not None:
        lines.append(f"`data/nifty100.csv` as of {universe['as_of'].iloc[0]}, "
                     f"{len(universe)} rows.\n")
    ok = True
    if args.official:
        ok &= check_official(universe, lines)
    if args.yahoo and universe is not None:
        ok &= check_yahoo(universe, lines)

    report = "\n".join(lines)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
