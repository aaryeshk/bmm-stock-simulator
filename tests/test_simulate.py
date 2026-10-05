import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bmm.simulate import (
    backtest,
    backtest_scores,
    backtest_window,
    bands,
    simulate,
    summary,
    theory,
    validation,
)
from bmm.trend import Assumptions, compute_trend, log_returns

FIX = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIX / "class_sample_simulation.json").read_text())


@pytest.fixture(scope="module")
def sample_sim():
    df = pd.read_csv(FIX / "class_reliance_nifty.csv", index_col="date", parse_dates=["date"])
    t = compute_trend(df["close"], df["index_close"], news_score=-0.5)
    return simulate(t.spot, t.mu, t.sigma, log_returns(df["close"]).to_numpy(), 60, 1000, 42)


# --- Regression: the verified class sample, path for path ------------------------------------

def test_scientific_paths_match_the_workbook(sample_sim):
    assert np.allclose(sample_sim.paths[:, 0], EXPECTED["path1"], rtol=1e-12)
    assert np.allclose(sample_sim.paths[-1], EXPECTED["paths_terminal"], rtol=1e-12)


def test_naive_paths_match_the_workbook(sample_sim):
    assert np.allclose(sample_sim.naive[-1], EXPECTED["naive_terminal"], rtol=1e-12)


@pytest.mark.parametrize("method", ["scientific", "naive"])
def test_summary_matches_the_workbook(sample_sim, method):
    got, exp = summary(sample_sim)[method], EXPECTED[method]
    for key, value in exp.items():
        assert got[key] == pytest.approx(value, rel=1e-9, abs=1e-12), key


def test_headline_numbers_of_the_sample(sample_sim):
    s = summary(sample_sim)["scientific"]
    assert round(s["median"]) == 1300           # median day-60 ~ Rs 1,300
    assert s["p_below"] == 0.57                  # P(below spot) 57%
    assert round(sample_sim.mu, 3) == -0.071     # final mu -7.1%


def test_bands_match_the_workbook(sample_sim):
    b = bands(sample_sim)
    mine = b[["day", "p5", "p25", "p50", "p75", "p95", "mean", "theory_mean",
              "naive_median"]].to_numpy()
    assert np.allclose(mine, np.array(EXPECTED["bands"], dtype=float), rtol=1e-12)


def test_validation_matches_the_workbook(sample_sim):
    v = validation(sample_sim)
    assert np.allclose(v["Theory"], EXPECTED["validation_theory"], rtol=1e-12)
    assert np.allclose(v["Simulated"], EXPECTED["validation_simulated"], rtol=1e-12)
    assert (v["Gap"].abs() < 0.05).all()         # sampling noise from 1,000 paths


# --- Hand calculation ----------------------------------------------------------------------

def test_exact_step_by_hand():
    sim = simulate(100.0, 0.10, 0.20, np.array([0.01, -0.02, 0.005]), horizon=20, n_paths=2,
                   seed=7)
    eps = np.random.default_rng(7).standard_normal((20, 2))
    dt = 1 / 255
    s = 100.0
    for d in range(20):
        s = s * math.exp((0.10 - 0.02) * dt + 0.20 * math.sqrt(dt) * eps[d, 1])
        assert sim.paths[d + 1, 1] == pytest.approx(s, rel=1e-13)
    assert np.array_equal(sim.shocks, eps)


def test_euler_step_by_hand():
    sim = simulate(100.0, 0.10, 0.20, np.array([0.01, -0.02]), horizon=20, n_paths=3, seed=3,
                   method="Euler")
    eps = sim.shocks
    s = 100.0
    for d in range(20):
        s = s * (1 + 0.10 / 255 + 0.20 * math.sqrt(1 / 255) * eps[d, 2])
    assert sim.paths[-1, 2] == pytest.approx(s, rel=1e-13)


def test_naive_bootstrap_by_hand():
    rets = np.array([0.01, -0.02, 0.03, 0.0])
    sim = simulate(50.0, 0.0, 0.2, rets, horizon=20, n_paths=4, seed=11)
    rng = np.random.default_rng(11)
    rng.standard_normal((20, 4))                         # shocks are drawn first
    rows = rng.integers(3, len(rets) + 3, size=(20, 4))  # workbook Prices rows 3..n_obs+1
    expected = 50.0 * np.exp(np.cumsum(rets[rows - 3], axis=0))
    assert np.allclose(sim.naive[1:], expected, rtol=1e-13)
    assert set(np.unique(sim.boot_index)) <= set(range(len(rets)))


def test_every_historical_return_can_be_drawn():
    rets = np.linspace(-0.01, 0.01, 10)
    sim = simulate(100.0, 0, 0.2, rets, horizon=100, n_paths=1000, seed=1)
    assert set(np.unique(sim.boot_index)) == set(range(10))  # first and last included


# --- Paths tilt with the trend --------------------------------------------------------------

@pytest.mark.parametrize("mu", [-0.30, -0.10, 0.0, 0.10, 0.30])
def test_median_tracks_theory(mu):
    sim = simulate(1000.0, mu, 0.25, np.array([0.0, 0.01]), horizon=60, n_paths=20000, seed=5)
    th = theory(sim)
    assert np.median(sim.paths[-1]) == pytest.approx(th["median"], rel=0.01)
    assert sim.paths[-1].mean() == pytest.approx(th["mean"], rel=0.01)


def test_paths_tilt_with_the_trend():
    hist = np.array([0.0, 0.01])
    down = simulate(1000.0, -0.30, 0.2, hist, seed=42)
    up = simulate(1000.0, 0.30, 0.2, hist, seed=42)
    assert np.median(down.paths[-1]) < 1000 < np.median(up.paths[-1])
    assert summary(down)["scientific"]["p_below"] > 0.5 > summary(up)["scientific"]["p_below"]
    # Same shocks, so every single path ends higher with the higher drift.
    assert (up.paths[-1] > down.paths[-1]).all()


def test_naive_ignores_the_trend_inputs():
    hist = np.random.default_rng(0).normal(0, 0.01, 400)
    a = simulate(1000.0, -0.30, 0.2, hist, seed=42)
    b = simulate(1000.0, 0.30, 0.2, hist, seed=42)
    assert np.array_equal(a.naive, b.naive)


def test_horizon_bounds():
    with pytest.raises(ValueError):
        simulate(100, 0, 0.2, np.array([0.0, 0.1]), horizon=10)
    sim = simulate(100, 0, 0.2, np.array([0.0, 0.1]), horizon=120)
    assert sim.paths.shape == (121, 1000) and sim.T == pytest.approx(120 / 255)


def test_probabilities_add_up(sample_sim):
    s = summary(sample_sim)["scientific"]
    assert s["p_below"] + s["p_above"] == pytest.approx(1.0)
    assert s["p_fall_10"] <= s["p_below"] and s["p_rise_10"] <= s["p_above"]


# --- Backtest ----------------------------------------------------------------------------------

def gbm_prices(n=520, mu=0.05, sigma=0.25, seed=0):
    rng = np.random.default_rng(seed)
    r = (mu - sigma**2 / 2) / 255 + sigma / math.sqrt(255) * rng.standard_normal(n - 1)
    return pd.Series(100 * np.exp(np.r_[0, np.cumsum(r)]),
                     index=pd.bdate_range("2024-01-01", periods=n))


def test_backtest_windows_end_on_the_latest_price():
    prices = gbm_prices()
    ws = backtest(prices, None, 60, Assumptions(), n_paths=200)
    assert ws[-1].end == prices.index[-1]
    assert all(w.start >= prices.index[255] for w in ws)
    assert len(ws) == (len(prices) - 1 - 60 - 255) // 20 + 1


def test_backtest_uses_no_future_data():
    prices = gbm_prices()
    w1 = backtest_window(prices, None, 300, 60, Assumptions(), n_paths=200)
    future_shock = prices.copy()
    future_shock.iloc[301:] *= 3          # change only the future
    w2 = backtest_window(future_shock, None, 300, 60, Assumptions(), n_paths=200)
    assert (w1.mu, w1.sigma) == (w2.mu, w2.sigma)
    assert w2.realised[-1] == pytest.approx(3 * w1.realised[-1])


def test_backtest_on_true_gbm_is_roughly_calibrated():
    # Prices really are GBM, so the realised price should land inside the 5-95% range most of
    # the time (exact 90% needs many independent windows; overlapping ones are noisy).
    rates = []
    for seed in range(6):
        prices = gbm_prices(n=900, seed=seed)
        rates.append(backtest_scores(backtest(prices, None, 60, Assumptions(), n_paths=300,
                                              step=60))["scientific"]["inside_rate"])
    assert 0.7 <= np.mean(rates) <= 1.0


def test_backtest_needs_enough_history():
    assert backtest(gbm_prices(n=300), None, 60, Assumptions()) == []
