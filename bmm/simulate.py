"""Brownian motion price paths: scientific (GBM) and naive (bootstrap), as in the class workbook.

Scientific (class Sheet 2), driven by mu and sigma from bmm.trend, dt = 1/255:
    Exact:  S(t+1) = S(t) x exp((mu - sigma^2/2) dt + sigma sqrt(dt) eps)
    Euler:  S(t+1) = S(t) x (1 + mu dt + sigma sqrt(dt) eps)          [class workbook method]
Naive (class Sheet 1): each day applies a randomly drawn historical daily log return.

Random numbers follow reference/bmm_export.py exactly, so a run with the same seed reproduces
the Excel export path for path: rng = default_rng(seed); first eps = rng.standard_normal(
(horizon, n_paths)), then the bootstrap draws = rng.integers(...). Days run down the rows and
paths across the columns, as in the workbook.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bmm.trend import DAYS_PER_YEAR, Assumptions, compute_trend, log_returns

N_PATHS = 1000
HORIZON_DEFAULT, HORIZON_MIN, HORIZON_MAX = 60, 20, 120
SEED = 42
PERCENTILES = (5, 25, 50, 75, 95)
METHODS = ("Exact", "Euler")


@dataclass(frozen=True)
class Simulation:
    spot: float
    mu: float
    sigma: float
    horizon: int
    method: str
    seed: int
    days_per_year: int
    shocks: np.ndarray          # (horizon, n_paths) standard normal draws
    boot_index: np.ndarray      # (horizon, n_paths) index into the historical log returns
    paths: np.ndarray           # (horizon + 1, n_paths) scientific, row 0 = spot
    naive: np.ndarray           # (horizon + 1, n_paths) bootstrap, row 0 = spot

    @property
    def dt(self) -> float:
        return 1 / self.days_per_year

    @property
    def T(self) -> float:
        return self.horizon / self.days_per_year


def simulate(spot: float, mu: float, sigma: float, hist_log_returns: np.ndarray | pd.Series,
             horizon: int = HORIZON_DEFAULT, n_paths: int = N_PATHS, seed: int = SEED,
             method: str = "Exact", days_per_year: int = DAYS_PER_YEAR) -> Simulation:
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if not HORIZON_MIN <= horizon <= 250:
        raise ValueError(f"horizon must be between {HORIZON_MIN} and 250 trading days")
    rets = np.asarray(hist_log_returns, dtype=float)
    if len(rets) < 2:
        raise ValueError("need historical log returns for the naive bootstrap")
    dt = 1 / days_per_year
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal((horizon, n_paths))
    # Workbook: Prices data rows 2..n_obs+1, returns on rows 3..n_obs+1; draw a row number in
    # that range (rng.integers' high is exclusive) and map it to a return index.
    n_obs = len(rets) + 1
    first_ret, last = 3, n_obs + 1
    boot_index = rng.integers(first_ret, last + 1, size=(horizon, n_paths)) - first_ret

    if method == "Exact":
        growth = np.exp((mu - sigma**2 / 2) * dt + sigma * math.sqrt(dt) * shocks)
    else:
        growth = 1 + mu * dt + sigma * math.sqrt(dt) * shocks
    paths = spot * np.vstack([np.ones(n_paths), np.cumprod(growth, axis=0)])
    naive = spot * np.vstack([np.ones(n_paths), np.cumprod(np.exp(rets[boot_index]), axis=0)])
    return Simulation(spot, mu, sigma, horizon, method, seed, days_per_year, shocks,
                      boot_index, paths, naive)


# --- Summaries ---------------------------------------------------------------------------------

def outcome(terminal: np.ndarray, spot: float) -> dict[str, float]:
    """Workbook Summary rows 5-16 for one set of terminal prices."""
    mean = float(terminal.mean())
    p5, median, p95 = (float(np.percentile(terminal, q)) for q in (5, 50, 95))
    n = len(terminal)
    return {"spot": spot, "mean": mean, "median": median, "p5": p5, "p95": p95,
            "expected_return": mean / spot - 1, "low_vs_spot": p5 / spot - 1,
            "high_vs_spot": p95 / spot - 1,
            "p_below": float((terminal < spot).sum() / n),
            "p_above": float((terminal > spot).sum() / n),
            "p_fall_10": float((terminal < spot * 0.9).sum() / n),
            "p_rise_10": float((terminal > spot * 1.1).sum() / n), "paths": n}


def summary(sim: Simulation) -> dict[str, dict[str, float]]:
    return {"scientific": outcome(sim.paths[-1], sim.spot),
            "naive": outcome(sim.naive[-1], sim.spot)}


def theory(sim: Simulation) -> dict[str, float]:
    """Closed-form GBM results (exact method) for the validation table."""
    t, mu, s = sim.T, sim.mu, sim.sigma
    log_mean, log_sd = (mu - s**2 / 2) * t, s * math.sqrt(t)
    return {"mean": sim.spot * math.exp(mu * t), "median": sim.spot * math.exp(log_mean),
            "p_below": 0.5 * math.erfc((log_mean / log_sd) / math.sqrt(2)) if log_sd else
            float(log_mean < 0), "log_sd": log_sd, "log_mean": log_mean}


def validation(sim: Simulation) -> pd.DataFrame:
    """Workbook Summary rows 20-24: theory vs simulated, with the gap."""
    th = theory(sim)
    out = summary(sim)["scientific"]
    log_t = np.log(sim.paths[-1] / sim.spot)
    rows = [("Mean price  S0·e^(μT)", th["mean"], out["mean"]),
            ("Median price  S0·e^((μ−σ²/2)T)", th["median"], out["median"]),
            ("P(ends below spot)", th["p_below"], out["p_below"]),
            ("Stdev of ln(S_T/S0)  σ√T", th["log_sd"], float(log_t.std(ddof=1))),
            ("Mean of ln(S_T/S0)  (μ−σ²/2)T", th["log_mean"], float(log_t.mean()))]
    df = pd.DataFrame(rows, columns=["Quantity", "Theory", "Simulated"])
    df["Gap"] = np.where(df["Theory"] == 0, 0.0, df["Simulated"] / df["Theory"] - 1)
    return df


def bands(sim: Simulation) -> pd.DataFrame:
    """Workbook Bands sheet: per-day percentiles, simulated and theoretical mean, naive median."""
    days = np.arange(sim.horizon + 1)
    df = pd.DataFrame({"day": days})
    for q, v in zip(PERCENTILES, np.percentile(sim.paths, PERCENTILES, axis=1), strict=True):
        df[f"p{q}"] = v
    df["mean"] = sim.paths.mean(axis=1)
    df["theory_mean"] = sim.spot * np.exp(sim.mu * days * sim.dt)
    df["naive_median"] = np.percentile(sim.naive, 50, axis=1)
    for q, v in zip((5, 95), np.percentile(sim.naive, (5, 95), axis=1), strict=True):
        df[f"naive_p{q}"] = v
    return df


# --- Backtest ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestWindow:
    start: pd.Timestamp           # last price date used for the estimate (day 0)
    end: pd.Timestamp
    spot: float
    realised: np.ndarray          # actual prices, day 0..horizon
    mu: float
    sigma: float
    bands: pd.DataFrame
    sci_rank: float               # share of simulated terminal prices below the realised one
    naive_rank: float
    sci_inside: bool              # realised terminal price inside the simulated 5-95% range
    naive_inside: bool
    sci_days_inside: float        # share of days the realised path stayed in the 5-95% band
    naive_days_inside: float
    sci_direction_right: bool     # median above spot and price rose, or below and fell
    naive_direction_right: bool


def backtest_window(prices: pd.Series, index: pd.Series | None, start_pos: int, horizon: int,
                    assumptions: Assumptions, method: str = "Exact", seed: int = SEED,
                    n_paths: int = N_PATHS) -> BacktestWindow:
    """Estimate mu and sigma using only prices up to start_pos (no news: historical headlines
    are not available), simulate `horizon` days ahead, and compare with what happened."""
    past = prices.iloc[: start_pos + 1]
    past_index = index.loc[: past.index[-1]] if index is not None else None
    trend = compute_trend(past, past_index, 0.0, assumptions)
    sim = simulate(float(past.iloc[-1]), trend.mu, trend.sigma, log_returns(past).to_numpy(),
                   horizon, n_paths, seed, method, assumptions.days_per_year)
    realised = prices.iloc[start_pos: start_pos + horizon + 1].to_numpy(dtype=float)
    b = bands(sim)
    final = realised[-1]

    def stats(term: np.ndarray, lo: np.ndarray, hi: np.ndarray, med: float):
        rank = float((term < final).mean())
        inside_end = bool(lo[-1] <= final <= hi[-1])
        days = float(((realised >= lo) & (realised <= hi))[1:].mean())
        right = (med > sim.spot) == (final > sim.spot)
        return rank, inside_end, days, bool(right)

    s = stats(sim.paths[-1], b["p5"].to_numpy(), b["p95"].to_numpy(), b["p50"].iloc[-1])
    n = stats(sim.naive[-1], b["naive_p5"].to_numpy(), b["naive_p95"].to_numpy(),
              b["naive_median"].iloc[-1])
    return BacktestWindow(past.index[-1], prices.index[start_pos + horizon], sim.spot, realised,
                          trend.mu, trend.sigma, b, s[0], n[0], s[1], n[1], s[2], n[2], s[3], n[3])


def backtest(prices: pd.Series, index: pd.Series | None, horizon: int, assumptions: Assumptions,
             method: str = "Exact", seed: int = SEED, min_history: int = 255, step: int = 20,
             n_paths: int = N_PATHS) -> list[BacktestWindow]:
    """Rolling windows: every `step` days from `min_history` onwards while the full horizon of
    realised prices exists. The last window ends on the latest price."""
    prices = prices.dropna()
    last_start = len(prices) - 1 - horizon
    if last_start < min_history:
        return []
    starts = list(range(last_start, min_history - 1, -step))[::-1]
    return [backtest_window(prices, index, s, horizon, assumptions, method, seed, n_paths)
            for s in starts]


def backtest_table(windows: list[BacktestWindow]) -> pd.DataFrame:
    rows = []
    for w in windows:
        rows.append({"Start": w.start.date(), "End": w.end.date(), "Spot": w.spot,
                     "Actual end": w.realised[-1], "μ used": w.mu, "σ used": w.sigma,
                     "Scientific: actual inside 5–95%": w.sci_inside,
                     "Naive: actual inside 5–95%": w.naive_inside,
                     "Scientific: direction right": w.sci_direction_right,
                     "Naive: direction right": w.naive_direction_right})
    return pd.DataFrame(rows)


def backtest_scores(windows: list[BacktestWindow]) -> dict[str, dict[str, float]]:
    if not windows:
        return {}
    def score(prefix: str) -> dict[str, float]:
        return {"inside_rate": float(np.mean([getattr(w, f"{prefix}_inside") for w in windows])),
                "days_inside": float(np.mean([getattr(w, f"{prefix}_days_inside")
                                              for w in windows])),
                "direction_rate": float(np.mean([getattr(w, f"{prefix}_direction_right")
                                                 for w in windows])),
                "windows": len(windows)}
    return {"scientific": score("sci"), "naive": score("naive")}
