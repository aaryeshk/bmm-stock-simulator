"""Download the bundled demo snapshot (Reliance + Nifty 50, 2 years) from Yahoo Finance.

Only one stock is bundled, to stay within Yahoo's terms for a public repo; every other stock
needs a live download or a CSV upload. Run by the Snapshot workflow, which commits the result.

    python scripts/make_snapshot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bmm.data import NIFTY_SYMBOL, fetch_yahoo, write_snapshot  # noqa: E402

DEMO = {"RELIANCE": "RELIANCE.NS", NIFTY_SYMBOL: NIFTY_SYMBOL}


def main() -> int:
    for symbol, yahoo_symbol in DEMO.items():
        meta = write_snapshot(symbol, fetch_yahoo(yahoo_symbol))
        print(f"{symbol}: {meta['rows']} rows, {meta['start']} to {meta['end']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
