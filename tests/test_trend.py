import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bmm.trend import (
    Assumptions,
    compute_trend,
    explain,
    label_for,
    log_returns,
    sigma_ewma,
    sigma_lookback,
    sigma_recent,
)

FIX = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIX / "class_sample_inputs.json").read_text())


@pytest.fixture(scope="module")
def class_data():
    df = pd.read_csv(FIX / "class_reliance_nifty.csv", index_col="date", parse_dates=["date"])
    return df["close"], df["index_close"]


@pytest.fixture(scope="module")
def sample_trend(class_data):
    stock, index = class_data
    return compute_trend(stock, index, news_score=EXPECTED["news_score"])


# --- Regression: the verified class sample (Inputs and Summary sheets) ------------------------

@pytest.mark.parametrize("key", ["historical", "momentum_3m", "momentum_6m", "capm"])
def test_components_match_the_workbook(sample_trend, key):
    c = {c.key: c for c in sample_trend.components}[key]
    assert c.mu == pytest.approx(EXPECTED[key], abs=1e-12)
    assert c.share == 0.25


def test_volatilities_match_the_workbook(sample_trend):
    assert sample_trend.sigma_method == "lookback"
    assert sample_trend.sigma == pytest.approx(EXPECTED["sigma_lookback"], abs=1e-12)
    assert sample_trend.sigmas["30d"] == pytest.approx(EXPECTED["sigma_30d"], abs=1e-12)


def test_beta_and_final_mu_match_the_workbook(sample_trend):
    assert sample_trend.beta == pytest.approx(EXPECTED["beta"], abs=1e-12)
    assert sample_trend.price_mu == pytest.approx(EXPECTED["price_mu"], abs=1e-12)
    assert sample_trend.news_adjustment == pytest.approx(EXPECTED["news_adjustment"])
    assert sample_trend.mu == pytest.approx(EXPECTED["mu"], abs=1e-12)  # -7.1%
    assert round(sample_trend.mu, 3) == -0.071
    assert sample_trend.label == EXPECTED["label"] == "Bearish"
    assert not sample_trend.clamped


def test_drift_vs_noise_matches_the_workbook(sample_trend):
    d = sample_trend.drift_vs_noise(60)
    for key in ("log_drift", "drift", "noise", "ratio"):
        assert d[key] == pytest.approx(EXPECTED[key], abs=1e-12), key


def test_technicals_match_the_workbook(sample_trend):
    t = sample_trend.technicals
    assert t.spot == EXPECTED["spot"]
    assert t.high_52w == pytest.approx(EXPECTED["high_52w"])
    assert t.from_high == pytest.approx(EXPECTED["from_high"], abs=1e-12)
    assert t.ma_50 == pytest.approx(EXPECTED["ma_50"], abs=1e-9)
    assert t.ma_200 == pytest.approx(EXPECTED["ma_200"], abs=1e-9)
    assert t.vol_ratio == pytest.approx(EXPECTED["vol_ratio"], abs=1e-12)
    assert t.vol_regime == EXPECTED["vol_regime"]


def test_closed_form_p_below_spot_is_consistent_with_the_sample(sample_trend):
    # Summary!B22: N(-(mu - sigma^2/2)T / sigma sqrt(T)) = 58.5%; the 1,000-path sample gave 57%.
    d = sample_trend.drift_vs_noise(60)
    p = 0.5 * math.erfc((d["drift"] / d["noise"]) / math.sqrt(2))
    assert p == pytest.approx(0.584817826946259, abs=1e-9)


# --- Hand calculation on a tiny series ---------------------------------------------------------

def test_hand_calculation_with_known_numbers():
    # 130 prices growing at a constant daily log return g: sigma = 0, so each price drift is
    # exactly g x 255 = 25.5%. No index, so beta = 1 and CAPM = 5% + 1 x 6% = 11%.
    g = 0.001
    idx = pd.bdate_range("2025-01-01", periods=130)
    stock = pd.Series(100 * np.exp(g * np.arange(130)), index=idx)
    a = Assumptions(risk_free=0.05, erp=0.06)
    t = compute_trend(stock, None, news_score=0.5, assumptions=a)
    assert t.sigma == pytest.approx(0, abs=1e-12)
    comp = {c.key: c.mu for c in t.components}
    for k in ("historical", "momentum_3m", "momentum_6m"):
        assert comp[k] == pytest.approx(0.255)
    assert comp["capm"] == pytest.approx(0.11)
    price_mu = (3 * 0.255 + 0.11) / 4                      # 21.875%
    assert t.price_mu == pytest.approx(price_mu)
    assert t.mu == pytest.approx(price_mu + 0.5 * 0.10)    # + news 0.5 x 10% = 26.875%
    assert t.label == "Bullish"


def test_flat_index_falls_back_to_beta_one():
    idx = pd.bdate_range("2025-01-01", periods=100)
    stock = pd.Series(np.linspace(100, 120, 100), index=idx)
    t = compute_trend(stock, pd.Series(1000.0, index=idx))
    assert t.beta == 1.0 and "no variance" in t.beta_note


def test_beta_hand_calculation():
    rng = np.random.default_rng(0)
    i_ret = rng.normal(0, 0.01, 300)
    s_ret = 1.5 * i_ret + rng.normal(0, 0.002, 300)
    idx = pd.bdate_range("2024-01-01", periods=301)
    index = pd.Series(1000 * np.exp(np.r_[0, np.cumsum(i_ret)]), index=idx)
    stock = pd.Series(100 * np.exp(np.r_[0, np.cumsum(s_ret)]), index=idx)
    t = compute_trend(stock, index)
    assert t.beta == pytest.approx(np.polyfit(i_ret, s_ret, 1)[0], abs=1e-12)
    capm = {c.key: c for c in t.components}["capm"]
    assert capm.mu == pytest.approx(0.0534 + t.beta * 0.07)


# --- Volatility estimators -------------------------------------------------------------------

def test_sigma_estimators():
    rng = np.random.default_rng(1)
    rets = pd.Series(rng.normal(0, 0.01, 500))
    assert sigma_lookback(rets) == pytest.approx(rets.std(ddof=1) * math.sqrt(255))
    assert sigma_recent(rets, 30) == pytest.approx(rets.iloc[-30:].std(ddof=1) * math.sqrt(255))
    assert sigma_recent(rets.iloc[:20], 30) is None
    # EWMA by hand
    var = rets.iloc[:30].var(ddof=1)
    for x in rets.iloc[30:]:
        var = 0.94 * var + 0.06 * x * x
    assert sigma_ewma(rets) == pytest.approx(math.sqrt(var * 255))


def test_ewma_reacts_to_a_volatility_spike():
    rng = np.random.default_rng(2)
    rets = pd.Series(np.r_[rng.normal(0, 0.01, 450), rng.normal(0, 0.03, 30)])
    assert sigma_ewma(rets) > 1.5 * sigma_lookback(rets)


@pytest.mark.parametrize("method", ["lookback", "30d", "ewma"])
def test_sigma_choice_flows_into_mu(class_data, method):
    stock, index = class_data
    t = compute_trend(stock, index, assumptions=Assumptions(sigma_method=method))
    assert t.sigma == t.sigmas[method]
    hist = {c.key: c for c in t.components}["historical"]
    assert hist.mu == pytest.approx(log_returns(stock).mean() * 255 + t.sigma**2 / 2)


# --- Rules: news, clamp, label, missing data ---------------------------------------------------

def test_news_adjustment_is_score_times_cap(class_data):
    stock, index = class_data
    base = compute_trend(stock, index, news_score=0)
    for score in (-1, -0.3, 0.4, 1):
        t = compute_trend(stock, index, news_score=score)
        assert t.mu - base.mu == pytest.approx(score * 0.10)
    assert compute_trend(stock, index, news_score=5).news_score == 1.0  # clipped


def test_mu_is_clamped_to_30_percent(class_data):
    stock, index = class_data
    a = Assumptions(risk_free=0.50, weights={"historical": 0, "momentum_3m": 0,
                                             "momentum_6m": 0, "capm": 1})
    t = compute_trend(stock, index, news_score=1, assumptions=a)
    assert t.mu_unclamped > 0.30 and t.mu == 0.30 and t.clamped
    assert any("clamped" in n for n in t.notes)


@pytest.mark.parametrize("mu,label", [(-0.051, "Bearish"), (-0.05, "Neutral"), (0, "Neutral"),
                                      (0.05, "Neutral"), (0.0501, "Bullish")])
def test_label_band(mu, label):
    assert label_for(mu, 0.05) == label


def test_weights_are_renormalised(class_data):
    stock, index = class_data
    a = Assumptions(weights={"historical": 2, "momentum_3m": 0, "momentum_6m": 0, "capm": 2})
    t = compute_trend(stock, index, assumptions=a)
    comp = {c.key: c for c in t.components}
    assert comp["historical"].share == comp["capm"].share == 0.5
    assert t.price_mu == pytest.approx((comp["historical"].mu + comp["capm"].mu) / 2)


def test_contributions_add_up_to_mu(sample_trend):
    total = sum(c.contribution for c in sample_trend.components) + sample_trend.news_adjustment
    assert total == pytest.approx(sample_trend.mu)


def test_missing_index_sets_beta_to_one(class_data):
    stock, _ = class_data
    t = compute_trend(stock, None)
    assert t.beta == 1.0 and "unavailable" in t.beta_note


def test_short_history_skips_6_month_momentum(class_data):
    stock, index = class_data
    t = compute_trend(stock.iloc[-100:], index)
    comp = {c.key: c for c in t.components}
    assert comp["momentum_6m"].mu is None and comp["momentum_6m"].share == 0
    assert comp["momentum_3m"].share == pytest.approx(1 / 3)
    assert any("6-month momentum skipped" in n for n in t.notes)


def test_too_short_history_is_an_error(class_data):
    with pytest.raises(ValueError, match="at least 31"):
        compute_trend(class_data[0].iloc[-20:])


def test_beta_uses_only_overlapping_dates(class_data):
    stock, index = class_data
    gappy = index.drop(index.index[::7])  # index missing every 7th day
    t = compute_trend(stock, gappy)
    # A pair needs the index on the day and on the stock's previous day: each gap drops 2 pairs.
    s_ret = np.log(stock / stock.shift(1))
    i_ret = np.log(gappy.reindex(stock.index) / gappy.reindex(stock.index).shift(1))
    pairs = pd.concat([s_ret, i_ret], axis=1).dropna()
    assert 0.8 < t.beta < 1.4 and f"Regression of {len(pairs)} daily" in t.beta_note
    assert t.beta == pytest.approx(np.polyfit(pairs.iloc[:, 1], pairs.iloc[:, 0], 1)[0])


# --- The "why" panel matches the inputs --------------------------------------------------------

def test_explanation_quotes_the_numbers(sample_trend):
    why = "\n".join(explain(sample_trend))
    assert "**Bearish**" in why and "-7.1%" in why
    assert "6-month momentum -19.1% × weight 25% = -4.8%" in why
    assert "News sentiment -0.50 × cap 10% = -5.0%" in why
    assert "β 1.06" in why and "21.1%" in why
    assert "-17.0% from its 52-week high" in why
