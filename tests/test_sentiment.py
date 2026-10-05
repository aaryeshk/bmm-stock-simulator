import pandas as pd
import pytest

from bmm.news import Headline
from bmm.sentiment import FULL_WEIGHT_AT, score_headlines, score_text

NOW = pd.Timestamp("2026-10-04", tz="UTC")


def h(title):
    return Headline(title, "P", "u", NOW, "google")


@pytest.mark.parametrize("title", [
    "Reliance stock falls 3%, Nifty slumps to six-month low",   # plain VADER scores this +0.15
    "Reliance hits fresh 52-week low as FII selling deepens",
    "Reliance shares slip as refining margins weaken",
    "Brokerage downgrades RIL, cuts target price",
    "Reliance faces SEBI probe over disclosure lapse",
    "Reliance Q2 profit misses estimates",
])
def test_bearish_headlines_score_negative(title):
    assert score_text(title) < -0.1


@pytest.mark.parametrize("title", [
    "RIL shares surge 5% on strong Q2 earnings beat",
    "Reliance Q2 profit rises 12% beating estimates",
    "Jio tariff hike lifts outlook; brokerages upgrade RIL",
    "Reliance hits 52-week high",
    "Reliance rallies as FII inflows return",
])
def test_bullish_headlines_score_positive(title):
    assert score_text(title) > 0.1


@pytest.mark.parametrize("title", ["Reliance announces AGM date",
                                   "Reliance to hold board meeting on October 17"])
def test_factual_headlines_are_neutral(title):
    assert abs(score_text(title)) < 0.05


def test_finance_lexicon_words_are_used():
    # 'litigation', 'impairment' and 'default' come from Loughran-McDonald, not VADER.
    assert score_text("Company reports impairment amid litigation and default risk") < -0.3


def test_score_is_the_average_when_there_are_enough_headlines():
    titles = ["Reliance surges", "Reliance plunges", "Reliance rallies", "Reliance gains",
              "Reliance announces AGM date"]
    s = score_headlines([h(t) for t in titles])
    assert s.count == 5
    assert s.score == pytest.approx(sum(score_text(t) for t in titles) / 5)
    assert s.raw_mean == s.score


def test_few_headlines_are_shrunk_towards_zero():
    one = score_headlines([h("Reliance plunges 8% after weak results")])
    assert one.count == 1
    assert one.score == pytest.approx(one.raw_mean / FULL_WEIGHT_AT)
    assert one.raw_mean < -0.5


def test_no_headlines_means_zero():
    s = score_headlines([])
    assert s.score == 0 and s.label == "No recent headlines"


def test_label():
    assert score_headlines([h("Reliance plunges")] * 5).label == "Negative"
    assert score_headlines([h("Reliance surges")] * 5).label == "Positive"
