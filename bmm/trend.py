"""Trend engine: annual drift mu and volatility sigma for the Brownian motion model.

Mirrors the class-layout workbook (reference/BMM_RELIANCE_60d_sample.xlsx, sheet Inputs) cell by
cell, so the app, the Excel export and a hand calculation agree:

    sigma (lookback)  = STDEV(daily log returns) x SQRT(255)               [default]
    sigma (30-day)    = STDEV(last 30 daily log returns) x SQRT(255)
    sigma (EWMA)      = RiskMetrics EWMA, lambda 0.94, annualised x SQRT(255)

    historical        = AVERAGE(daily log returns) x 255 + sigma^2/2
    3-month momentum  = LN(S0 / S[-63])  x 255/63  + sigma^2/2
    6-month momentum  = LN(S0 / S[-126]) x 255/126 + sigma^2/2
    CAPM              = r + beta x ERP,  beta = SLOPE(stock log returns, Nifty log returns)
    price-trend mu    = weighted average of the four (weights default 0.25 each)
    news adjustment   = sentiment score (-1..+1) x cap (10%/yr)
    FINAL mu          = price-trend mu + news adjustment, clamped to +/-30%/yr

The +sigma^2/2 terms turn log-return drifts into the arithmetic drift mu that the exact GBM
step S x exp((mu - sigma^2/2)dt + sigma sqrt(dt) eps) expects. sigma is whichever volatility
is in use, as on the workbook's "Volatility used" row.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 255
SIGMA_METHODS = {"lookback": "Lookback (2-year) historical", "30d": "30-day",
                 "ewma": "EWMA (λ 0.94)"}
COMPONENTS = ("historical", "momentum_3m", "momentum_6m", "capm")
COMPONENT_LABELS = {"historical": "Historical drift", "momentum_3m": "3-month momentum",
                    "momentum_6m": "6-month momentum", "capm": "CAPM expected return"}
MOMENTUM_DAYS = {"momentum_3m": 63, "momentum_6m": 126}


@dataclass(frozen=True)
class Assumptions:
    """Everything a user can change. Defaults follow the locked plan."""
    risk_free: float = 0.0534            # 91-day T-bill cut-off yield (RBI)
    risk_free_note: str = "91-day T-bill cut-off yield (RBI)"
    erp: float = 0.07                    # equity risk premium, India
    weights: dict[str, float] = field(default_factory=lambda: dict.fromkeys(COMPONENTS, 0.25))
    news_cap: float = 0.10               # max drift change from news, per year
    mu_limit: float = 0.30               # final mu is clamped to +/- this
    neutral_band: float = 0.05           # |mu| within this = Neutral
    sigma_method: str = "lookback"
    ewma_lambda: float = 0.94
    recent_days: int = 30
    days_per_year: int = DAYS_PER_YEAR

    def with_(self, **changes) -> Assumptions:
        return replace(self, **changes)


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    mu: float | None          # annual drift, None when there is not enough history
    weight: float             # as set by the user
    share: float              # weight / total weight of available components
    contribution: float       # mu x share
    how: str                  # formula in words, with the numbers used


@dataclass(frozen=True)
class Technicals:
    spot: float
    high_52w: float
    low_52w: float
    from_high: float          # spot / 52w high - 1
    range_position: float     # 0 = at 52w low, 1 = at 52w high
    ma_50: float | None
    ma_200: float | None
    sigma_lookback: float
    sigma_recent: float | None
    vol_ratio: float | None   # 30-day / lookback - 1
    vol_regime: str           # Elevated | Subdued | In line | Unknown


@dataclass(frozen=True)
class Trend:
    spot: float
    as_of: pd.Timestamp
    sigma: float
    sigma_method: str
    sigmas: dict[str, float | None]
    beta: float
    beta_note: str
    components: tuple[Component, ...]
    price_mu: float
    news_score: float
    news_adjustment: float
    mu_unclamped: float
    mu: float
    clamped: bool
    label: str
    technicals: Technicals
    assumptions: Assumptions
    notes: tuple[str, ...]

    def drift_vs_noise(self, horizon_days: int) -> dict[str, float]:
        """Workbook rows 38-41: log drift, drift and noise over the horizon, and their ratio."""
        t = horizon_days / self.assumptions.days_per_year
        log_drift = self.mu - self.sigma**2 / 2
        noise = self.sigma * math.sqrt(t)
        return {"log_drift": log_drift, "drift": log_drift * t, "noise": noise,
                "ratio": abs(log_drift * t) / noise if noise else float("inf"), "T": t}


def log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices / prices.shift(1)).dropna()


def sigma_lookback(rets: pd.Series, days_per_year: int = DAYS_PER_YEAR) -> float:
    return float(rets.std(ddof=1) * math.sqrt(days_per_year))


def sigma_recent(rets: pd.Series, n: int = 30, days_per_year: int = DAYS_PER_YEAR) -> float | None:
    return float(rets.iloc[-n:].std(ddof=1) * math.sqrt(days_per_year)) if len(rets) >= n else None


def sigma_ewma(rets: pd.Series, lam: float = 0.94, days_per_year: int = DAYS_PER_YEAR,
               seed_days: int = 30) -> float | None:
    """RiskMetrics: var_t = lam var_{t-1} + (1-lam) r_{t-1}^2, seeded with the sample variance of
    the first `seed_days` returns. Returns the forecast for the next day, annualised."""
    if len(rets) <= seed_days:
        return None
    r = rets.to_numpy()
    var = float(np.var(r[:seed_days], ddof=1))
    for x in r[seed_days:]:
        var = lam * var + (1 - lam) * x * x
    return math.sqrt(var * days_per_year)


def beta_vs_index(stock: pd.Series, index: pd.Series | None) -> tuple[float, str]:
    """SLOPE of stock log returns on index log returns, as the Excel export computes it.

    The index is lined up on the stock's trading dates; a day's pair is used only when the
    index has a price on that day and on the stock's previous trading day (Excel's SLOPE skips
    the blank cells the export leaves on other days)."""
    if index is None:
        return 1.0, "Nifty 50 data unavailable, so beta is set to 1.0."
    both = pd.DataFrame({"s": stock, "i": index.reindex(stock.index)})
    rets = np.log(both / both.shift(1)).dropna()
    if len(rets) < 30:
        return 1.0, f"Only {len(rets)} overlapping days with the Nifty 50, so beta is set to 1.0."
    cov = np.cov(rets["s"], rets["i"], ddof=1)
    if not cov[1, 1] > 1e-12:
        return 1.0, "Nifty 50 returns have no variance in this window, so beta is set to 1.0."
    return float(cov[0, 1] / cov[1, 1]), f"Regression of {len(rets)} daily log returns vs Nifty 50."


def technicals(prices: pd.Series, sigma_lb: float, sigma_rc: float | None,
               days_per_year: int = DAYS_PER_YEAR) -> Technicals:
    spot = float(prices.iloc[-1])
    year = prices.iloc[-days_per_year:]
    hi, lo = float(year.max()), float(year.min())
    ma = {n: float(prices.iloc[-n:].mean()) if len(prices) >= n else None for n in (50, 200)}
    ratio = sigma_rc / sigma_lb - 1 if sigma_rc is not None and sigma_lb else None
    regime = ("Unknown" if ratio is None else "Elevated" if ratio > 0.15
              else "Subdued" if ratio < -0.15 else "In line")
    return Technicals(spot, hi, lo, spot / hi - 1, (spot - lo) / (hi - lo) if hi > lo else 0.5,
                      ma[50], ma[200], sigma_lb, sigma_rc, ratio, regime)


def label_for(mu: float, band: float) -> str:
    return "Bearish" if mu < -band else "Bullish" if mu > band else "Neutral"


def compute_trend(prices: pd.Series, index: pd.Series | None = None, news_score: float = 0.0,
                  assumptions: Assumptions | None = None) -> Trend:
    """prices / index: adjusted closes with a DatetimeIndex, ascending."""
    a = assumptions or Assumptions()
    if a.sigma_method not in SIGMA_METHODS:
        raise ValueError(f"sigma_method must be one of {list(SIGMA_METHODS)}")
    prices = prices.dropna()
    if len(prices) < 31:
        raise ValueError(f"Need at least 31 prices to estimate a trend, got {len(prices)}.")
    notes: list[str] = []
    n = a.days_per_year
    rets = log_returns(prices)
    spot = float(prices.iloc[-1])

    sigmas = {"lookback": sigma_lookback(rets, n),
              "30d": sigma_recent(rets, a.recent_days, n),
              "ewma": sigma_ewma(rets, a.ewma_lambda, n)}
    sigma, method = sigmas[a.sigma_method], a.sigma_method
    if sigma is None:
        sigma, method = sigmas["lookback"], "lookback"
        notes.append(f"Not enough history for {SIGMA_METHODS[a.sigma_method]} volatility; "
                     "using lookback volatility.")
    half_var = sigma**2 / 2

    beta, beta_note = beta_vs_index(prices, index)
    raw = {
        "historical": (float(rets.mean()) * n + half_var,
                       f"mean daily log return {rets.mean():+.5f} × {n} + σ²/2 ({half_var:.4f})"),
        "capm": (a.risk_free + beta * a.erp,
                 f"r {a.risk_free:.2%} + β {beta:.2f} × ERP {a.erp:.2%}"),
    }
    for key, days in MOMENTUM_DAYS.items():
        if len(prices) > days:
            past = float(prices.iloc[-1 - days])
            raw[key] = (math.log(spot / past) * n / days + half_var,
                        f"ln({spot:,.2f} / {past:,.2f}) × {n}/{days} + σ²/2")
        else:
            raw[key] = (None, f"needs more than {days} trading days of prices")
            notes.append(f"{COMPONENT_LABELS[key]} skipped: only {len(prices)} prices.")

    total = sum(a.weights.get(k, 0) for k in COMPONENTS if raw[k][0] is not None)
    if total <= 0:
        raise ValueError("At least one available drift component needs a positive weight.")
    components = []
    for k in COMPONENTS:
        mu_k, how = raw[k]
        w = float(a.weights.get(k, 0))
        share = w / total if mu_k is not None else 0.0
        components.append(Component(k, COMPONENT_LABELS[k], mu_k, w, share,
                                    (mu_k or 0.0) * share, how))
    price_mu = sum(c.contribution for c in components)

    news_score = max(-1.0, min(1.0, float(news_score)))
    news_adj = news_score * a.news_cap
    mu_unclamped = price_mu + news_adj
    mu = max(-a.mu_limit, min(a.mu_limit, mu_unclamped))
    clamped = mu != mu_unclamped
    if clamped:
        notes.append(f"Drift {mu_unclamped:+.1%} was clamped to {mu:+.1%} "
                     f"(limit ±{a.mu_limit:.0%}).")

    return Trend(spot=spot, as_of=prices.index[-1], sigma=sigma, sigma_method=method,
                 sigmas=sigmas, beta=beta, beta_note=beta_note, components=tuple(components),
                 price_mu=price_mu, news_score=news_score, news_adjustment=news_adj,
                 mu_unclamped=mu_unclamped, mu=mu, clamped=clamped,
                 label=label_for(mu, a.neutral_band),
                 technicals=technicals(prices, sigmas["lookback"], sigmas["30d"], n),
                 assumptions=a, notes=tuple(notes))


def explain(trend: Trend) -> list[str]:
    """Plain-language 'why' lines, each tied to a number the user can see."""
    a, t = trend.assumptions, trend.technicals
    lines = [f"**{trend.label}**: final drift μ = {trend.mu:+.1%} a year "
             f"(neutral band ±{a.neutral_band:.0%})."]
    for c in sorted(trend.components, key=lambda c: -abs(c.contribution)):
        if c.mu is None:
            lines.append(f"{c.label}: not used ({c.how}).")
        else:
            lines.append(f"{c.label} {c.mu:+.1%} × weight {c.share:.0%} = "
                         f"{c.contribution:+.1%}  ·  {c.how}.")
    if trend.news_adjustment:
        lines.append(f"News sentiment {trend.news_score:+.2f} × cap {a.news_cap:.0%} = "
                     f"{trend.news_adjustment:+.1%}.")
    else:
        lines.append("News adjustment 0 (no score or neutral headlines).")
    if trend.clamped:
        lines.append(f"Clamped from {trend.mu_unclamped:+.1%} to the ±{a.mu_limit:.0%} limit.")
    lines.append(f"Volatility σ = {trend.sigma:.1%} ({SIGMA_METHODS[trend.sigma_method]}); "
                 f"30-day vs lookback: {t.vol_regime.lower()}.")
    pos = "above" if t.ma_200 and t.spot > t.ma_200 else "below"
    lines.append(f"Price {t.from_high:+.1%} from its 52-week high, {pos} its 200-day average.")
    return lines
