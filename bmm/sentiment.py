"""Headline sentiment: VADER with the Loughran-McDonald finance lexicon and market-move words.

VADER alone is tuned for social media and misreads market news ("stock falls 3%, Nifty slumps
to six-month low" scores positive). Two word lists are layered on top of its lexicon:

1. Loughran-McDonald (data/lm_lexicon.csv): 2,709 finance words, positive +1.5 / negative -1.5,
   added where VADER has no entry. Source: Loughran & McDonald Master Dictionary, Notre Dame
   SRAF (as distributed with pysentiment2), used for education and research.
2. Market moves (data/market_lexicon.csv): ~90 price-move words (falls, slumps, surges, 52-week
   low/high, upgrade, ...) that always override, with VADER-scale valences.

Each headline gets VADER's compound score in [-1, 1]. The stock's score is their average,
shrunk towards 0 when there are fewer than 5 headlines so one story cannot set the full news
adjustment.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from bmm.news import Headline

DATA = Path(__file__).resolve().parents[1] / "data"
LM_VALENCE = 1.5
FULL_WEIGHT_AT = 5  # headlines needed before the score is used at full strength


@dataclass(frozen=True)
class ScoredHeadline:
    headline: Headline
    score: float


@dataclass(frozen=True)
class Sentiment:
    score: float                      # -1 (very bearish) .. +1 (very bullish), after shrinkage
    raw_mean: float                   # average headline score before shrinkage
    count: int
    scored: tuple[ScoredHeadline, ...]

    @property
    def label(self) -> str:
        if self.count == 0:
            return "No recent headlines"
        if self.score <= -0.05:
            return "Negative"
        if self.score >= 0.05:
            return "Positive"
        return "Neutral"


@lru_cache(maxsize=1)
def analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    a = SentimentIntensityAnalyzer()
    lm = pd.read_csv(DATA / "lm_lexicon.csv")
    for word, polarity in zip(lm["word"], lm["polarity"], strict=True):
        a.lexicon.setdefault(word, LM_VALENCE * polarity)
    market = pd.read_csv(DATA / "market_lexicon.csv")
    a.lexicon.update(dict(zip(market["word"], market["valence"], strict=True)))
    return a


def score_text(text: str) -> float:
    return float(analyzer().polarity_scores(text)["compound"])


def score_headlines(headlines: tuple[Headline, ...] | list[Headline]) -> Sentiment:
    scored = tuple(ScoredHeadline(h, score_text(h.title)) for h in headlines)
    if not scored:
        return Sentiment(0.0, 0.0, 0, ())
    raw = sum(s.score for s in scored) / len(scored)
    shrink = min(1.0, len(scored) / FULL_WEIGHT_AT)
    return Sentiment(max(-1.0, min(1.0, raw * shrink)), raw, len(scored), scored)
