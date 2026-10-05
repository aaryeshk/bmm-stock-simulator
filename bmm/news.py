"""Recent headlines for a stock from Yahoo Finance and Google News, merged and de-duplicated.

News never blocks the app: every failure becomes a note and an empty or partial list.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import pandas as pd
import requests

from bmm.cache import FIFTEEN_MINUTES, ttl_cache
from bmm.data import offline

DAYS = 14
LIMIT = 20
GOOGLE_RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; bmm-stock-simulator)"}


@dataclass(frozen=True)
class Headline:
    title: str
    publisher: str
    url: str
    published: pd.Timestamp  # UTC
    source: str              # "yahoo" | "google"


@dataclass(frozen=True)
class News:
    headlines: tuple[Headline, ...]
    notes: tuple[str, ...]


def _ts(value) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int | float):
            return pd.Timestamp(value, unit="s", tz="UTC")
        ts = pd.Timestamp(value)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    except (ValueError, TypeError):
        return None


def parse_yahoo_news(items: list[dict]) -> list[Headline]:
    """Handle both yfinance news formats (flat pre-0.2.50, nested `content` after)."""
    out = []
    for item in items or []:
        c = item.get("content", item)
        title = (c.get("title") or "").strip()
        provider = c.get("provider") or {}
        publisher = provider.get("displayName") if isinstance(provider, dict) else None
        publisher = publisher or c.get("publisher") or "Yahoo Finance"
        url = ((c.get("canonicalUrl") or {}).get("url")
               or (c.get("clickThroughUrl") or {}).get("url") or c.get("link") or "")
        published = _ts(c.get("pubDate") or c.get("displayTime") or c.get("providerPublishTime"))
        if title and published is not None:
            out.append(Headline(title, publisher, url, published, "yahoo"))
    return out


def parse_google_rss(xml_text: str) -> list[Headline]:
    out = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = item.find("source")
        publisher = (source.text or "").strip() if source is not None else ""
        # Google appends " - Publisher" to every title.
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        try:
            published = pd.Timestamp(parsedate_to_datetime(item.findtext("pubDate") or ""))
            published = published.tz_convert("UTC")
        except (TypeError, ValueError):
            continue
        if title:
            out.append(Headline(title, publisher or "Google News", item.findtext("link") or "",
                                published, "google"))
    return out


def google_query(name: str) -> str:
    """'Reliance Industries Ltd' -> '"Reliance Industries" share OR stock OR NSE'."""
    short = re.sub(r"\b(Ltd|Limited|Co|Company)\.?$", "", name.strip()).strip(" .")
    return f'"{short}" share OR stock OR NSE when:{DAYS}d'


def fetch_yahoo_news(yahoo_symbol: str) -> list[Headline]:
    import yfinance as yf

    return parse_yahoo_news(yf.Ticker(yahoo_symbol).news)


def fetch_google_news(name: str) -> list[Headline]:
    r = requests.get(GOOGLE_RSS.format(q=quote_plus(google_query(name))), headers=HEADERS,
                     timeout=15)
    r.raise_for_status()
    return parse_google_rss(r.text)


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())[:80]


def merge(lists: list[list[Headline]], now: pd.Timestamp, days: int = DAYS,
          limit: int = LIMIT) -> list[Headline]:
    cutoff = now - pd.Timedelta(days=days)
    seen, out = set(), []
    for h in sorted((h for hs in lists for h in hs), key=lambda h: h.published, reverse=True):
        k = _key(h.title)
        if h.published >= cutoff and k not in seen:
            seen.add(k)
            out.append(h)
    return out[:limit]


@ttl_cache(FIFTEEN_MINUTES)
def get_headlines(yahoo_symbol: str, name: str) -> News:
    if offline():
        return News((), ("Headlines are off in offline mode.",))
    lists, notes = [], []
    for label, fetch, arg in (("Yahoo Finance", fetch_yahoo_news, yahoo_symbol),
                              ("Google News", fetch_google_news, name)):
        try:
            lists.append(fetch(arg))
        except Exception as exc:  # network, HTTP, parse errors: news is best effort
            notes.append(f"{label} headlines unavailable ({type(exc).__name__}).")
    headlines = merge(lists, pd.Timestamp.now(tz="UTC"))
    if not headlines:
        notes.append(f"No headlines found in the last {DAYS} days.")
    return News(tuple(headlines), tuple(notes))
