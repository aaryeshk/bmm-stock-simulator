"""Daily price history: Yahoo Finance first, then the bundled snapshot, else a user upload.

Every series comes back as a PriceHistory whose frame has a DatetimeIndex named `date` and at
least an `adj_close` column (Yahoo adds open/high/low/close/volume). Adjusted close is used for
all returns so splits and dividends do not show up as fake jumps.
"""
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from bmm.cache import FIFTEEN_MINUTES, ttl_cache

YEARS = 2
MIN_ROWS = 60
NIFTY_SYMBOL = "^NSEI"
SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshots"
COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]
UPLOAD_HELP = ("CSV with a Date column and an Adj Close column (Close is accepted if there is "
               "no Adj Close). One row per trading day; at least 60 rows, ideally 2 years.")


class DataUnavailable(Exception):
    """No price history could be obtained from any source."""


class UploadError(ValueError):
    """An uploaded CSV could not be used. The message is shown to the user."""


@dataclass(frozen=True)
class PriceHistory:
    symbol: str
    frame: pd.DataFrame
    source: str                      # "yahoo" | "snapshot" | "upload"
    fetched_at: pd.Timestamp         # UTC
    notes: tuple[str, ...] = field(default=())

    @property
    def adj_close(self) -> pd.Series:
        return self.frame["adj_close"]

    @property
    def start(self) -> pd.Timestamp:
        return self.frame.index[0]

    @property
    def end(self) -> pd.Timestamp:
        return self.frame.index[-1]

    def __len__(self) -> int:
        return len(self.frame)

    @property
    def source_label(self) -> str:
        return {"yahoo": "Yahoo Finance (live)", "snapshot": "Bundled snapshot",
                "upload": "Your upload"}[self.source]


def offline() -> bool:
    """BMM_OFFLINE=1 skips every network call (tests, demos without internet)."""
    return os.environ.get("BMM_OFFLINE", "") not in ("", "0")


def clean_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Sorted, de-duplicated daily rows with a positive adjusted close."""
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    df.index.name = "date"
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[[c for c in COLUMNS if c in df.columns]]
    df = df[df["adj_close"].notna() & (df["adj_close"] > 0)]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


# --- Yahoo Finance -----------------------------------------------------------------------------

def fetch_yahoo(yahoo_symbol: str, years: int = YEARS) -> pd.DataFrame:
    """Download daily OHLC + adjusted close. Raises DataUnavailable on any failure."""
    if offline():
        raise DataUnavailable("offline mode")
    try:
        import yfinance as yf

        raw = yf.Ticker(yahoo_symbol).history(period=f"{years}y", interval="1d",
                                              auto_adjust=False, actions=False)
    except Exception as exc:  # yfinance raises many types: HTTP, rate limit, JSON, ...
        raise DataUnavailable(f"Yahoo Finance error: {type(exc).__name__}: {exc}") from exc
    if raw is None or raw.empty:
        raise DataUnavailable("Yahoo Finance returned no data")
    raw = raw.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close",
                              "Adj Close": "adj_close", "Volume": "volume"})
    if "adj_close" not in raw.columns:
        raw["adj_close"] = raw["close"]
    df = clean_prices(raw)
    if len(df) < MIN_ROWS:
        raise DataUnavailable(f"Yahoo Finance returned only {len(df)} days")
    return df


@ttl_cache(FIFTEEN_MINUTES, failure_seconds=120)
def _yahoo_cached(yahoo_symbol: str, years: int) -> tuple[pd.DataFrame, pd.Timestamp]:
    return fetch_yahoo(yahoo_symbol, years), pd.Timestamp.now(tz="UTC")


# --- Bundled snapshot --------------------------------------------------------------------------

def snapshot_path(symbol: str) -> Path:
    return SNAPSHOT_DIR / f"{re.sub(r'[^A-Za-z0-9]', '', symbol)}.csv"


def snapshot_manifest() -> dict:
    path = SNAPSHOT_DIR / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def has_snapshot(symbol: str) -> bool:
    return snapshot_path(symbol).exists()


def load_snapshot(symbol: str) -> PriceHistory:
    path = snapshot_path(symbol)
    if not path.exists():
        raise DataUnavailable(f"no bundled snapshot for {symbol}")
    frame = clean_prices(pd.read_csv(path, index_col="date", parse_dates=["date"]))
    meta = snapshot_manifest().get(symbol, {})
    fetched = (pd.Timestamp(meta["fetched_at"]) if "fetched_at" in meta
               else pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC"))
    return PriceHistory(symbol, frame, "snapshot", fetched)


def write_snapshot(symbol: str, frame: pd.DataFrame, source: str = "Yahoo Finance") -> dict:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(snapshot_path(symbol), float_format="%.4f", date_format="%Y-%m-%d")
    manifest = snapshot_manifest()
    manifest[symbol] = {"source": source, "fetched_at": pd.Timestamp.now(tz="UTC").isoformat(),
                        "start": str(frame.index[0].date()), "end": str(frame.index[-1].date()),
                        "rows": len(frame)}
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest[symbol]


# --- User upload -------------------------------------------------------------------------------

def _header_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", str(name).lower())


def parse_upload(content: bytes | str, symbol: str = "UPLOAD") -> PriceHistory:
    """Parse a user CSV (Date + Adj Close). Raises UploadError with a readable message."""
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    try:
        raw = pd.read_csv(io.StringIO(text), dtype=str, skipinitialspace=True)
    except Exception as exc:
        raise UploadError(f"Could not read the file as CSV ({exc}).") from exc
    cols = {_header_key(c): c for c in raw.columns}
    date_col = cols.get("date")
    if date_col is None:
        raise UploadError(f"No Date column found. Columns were: {', '.join(raw.columns)}.")
    notes = []
    price_col = cols.get("adjclose") or cols.get("adjustedclose")
    if price_col is None and "close" in cols:
        price_col = cols["close"]
        notes.append("No Adj Close column, so Close was used. Splits or dividends in the period "
                     "will show up as price jumps.")
    if price_col is None:
        raise UploadError(f"No Adj Close (or Close) column found. Columns were: "
                          f"{', '.join(raw.columns)}.")

    dates = _parse_dates(raw[date_col])
    prices = pd.to_numeric(raw[price_col].str.replace(",", "", regex=False).str.strip(),
                           errors="coerce")
    frame = pd.DataFrame({"adj_close": prices.to_numpy()}, index=pd.DatetimeIndex(dates))
    frame = clean_prices(frame[frame.index.notna()])
    dropped = len(raw) - len(frame)
    if dropped:
        notes.append(f"{dropped} row(s) with a missing date, missing price or duplicate date "
                     "were skipped.")
    if len(frame) < MIN_ROWS:
        raise UploadError(f"Only {len(frame)} usable rows; at least {MIN_ROWS} trading days are "
                          "needed.")
    return PriceHistory(symbol, frame, "upload", pd.Timestamp.now(tz="UTC"), tuple(notes))


def _parse_dates(col: pd.Series) -> pd.Series:
    col = col.str.strip()
    try:
        return pd.to_datetime(col, format="ISO8601")
    except (ValueError, TypeError):
        pass
    # Indian exports are day-first (18/08/2026, 18-Aug-2026).
    parsed = pd.to_datetime(col, dayfirst=True, format="mixed", errors="coerce")
    if parsed.isna().all():
        raise UploadError("Could not understand the dates. Use YYYY-MM-DD or DD/MM/YYYY.")
    return parsed


# --- Public entry points -----------------------------------------------------------------------

def get_prices(symbol: str, yahoo_symbol: str, upload: bytes | None = None,
               years: int = YEARS) -> PriceHistory:
    """Upload if given, else Yahoo (cached 15 minutes), else the bundled snapshot."""
    if upload is not None:
        return parse_upload(upload, symbol)
    try:
        frame, fetched = _yahoo_cached(yahoo_symbol, years)
        return PriceHistory(symbol, frame, "yahoo", fetched)
    except DataUnavailable as exc:
        reason = str(exc)
    if has_snapshot(symbol):
        snap = load_snapshot(symbol)
        note = (f"Live prices are unavailable ({reason}), so the bundled snapshot to "
                f"{snap.end:%d-%b-%Y} is shown.")
        return PriceHistory(symbol, snap.frame, "snapshot", snap.fetched_at, (note,))
    raise DataUnavailable(f"Couldn't get prices for {symbol} from Yahoo Finance ({reason}). "
                          f"Upload a CSV instead: {UPLOAD_HELP}")


def get_index_prices(upload: bytes | None = None, years: int = YEARS) -> PriceHistory:
    """Nifty 50 index, used for beta. Same fallback chain as get_prices."""
    return get_prices(NIFTY_SYMBOL, NIFTY_SYMBOL, upload, years)
