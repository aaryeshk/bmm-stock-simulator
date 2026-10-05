"""The Nifty 100 universe: a dated snapshot of index constituents with search metadata.

data/nifty100.csv columns:
    symbol        NSE trading symbol (e.g. M&M)
    yahoo_symbol  Yahoo Finance symbol (e.g. M&M.NS)
    name          Company name
    sector        NSE industry classification
    group         Business group (Tata, Adani, ...) or blank
    aliases       Common nicknames, pipe-separated (e.g. RIL|Reliance)
    isin          ISIN code
    as_of         Date the constituent list was taken from NSE (same on every row)
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

UNIVERSE_CSV = Path(__file__).resolve().parents[1] / "data" / "nifty100.csv"
COLUMNS = ["symbol", "yahoo_symbol", "name", "sector", "group", "aliases", "isin", "as_of"]


@dataclass(frozen=True)
class Stock:
    symbol: str
    yahoo_symbol: str
    name: str
    sector: str
    group: str
    aliases: tuple[str, ...]
    isin: str

    @property
    def label(self) -> str:
        """Dropdown label: Company name (TICKER) · Sector."""
        return f"{self.name} ({self.symbol}) · {self.sector}"


@lru_cache(maxsize=1)
def load_universe(path: Path = UNIVERSE_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if df["symbol"].duplicated().any():
        raise ValueError(f"{path.name} has duplicate symbols: "
                         f"{sorted(df.loc[df['symbol'].duplicated(), 'symbol'])}")
    if df["as_of"].nunique() != 1:
        raise ValueError(f"{path.name} must have a single as_of date")
    return df[COLUMNS]


@lru_cache(maxsize=1)
def stocks() -> tuple[Stock, ...]:
    return tuple(
        Stock(
            symbol=r.symbol,
            yahoo_symbol=r.yahoo_symbol,
            name=r.name,
            sector=r.sector,
            group=r.group,
            aliases=tuple(a.strip() for a in r.aliases.split("|") if a.strip()),
            isin=r.isin,
        )
        for r in load_universe().itertuples(index=False)
    )


def as_of() -> str:
    return load_universe()["as_of"].iloc[0]
