"""Resolve free-text queries to Nifty 100 stocks.

Order of precedence (first rule that hits wins):
    1. Exact ticker            RELIANCE, m&m, bajaj-auto, RELIANCE.NS
    2. Exact alias             RIL, HUL, SBI, Mahindra
    3. Exact company name      Reliance Industries, reliance industries ltd
    4. Business group          Tata, Adani, Bajaj  -> pick from the group
    5. Word prefix             Hindustan, Kotak    -> load if one hit, else pick
    6. Fuzzy (typos)           Relaince            -> "did you mean" pick list
Anything else is outside the universe: rejected, with the closest Nifty 100 names as suggestions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz, process

from bmm.universe import Stock, stocks

FUZZY_PICK = 85      # score at which a typo is offered as "did you mean"
FUZZY_SUGGEST = 70   # score at which a stock is suggested alongside a rejection
MAX_CHOICES = 12

# Well-known non-Nifty names mapped to the NSE sector we suggest peers from.
GLOBAL_PEERS = {
    "AAPL": "Information Technology", "APPLE": "Information Technology",
    "MSFT": "Information Technology", "MICROSOFT": "Information Technology",
    "GOOGL": "Information Technology", "GOOG": "Information Technology",
    "GOOGLE": "Information Technology", "ALPHABET": "Information Technology",
    "META": "Information Technology", "NVDA": "Information Technology",
    "NVIDIA": "Information Technology", "IBM": "Information Technology",
    "ACCENTURE": "Information Technology", "ACN": "Information Technology",
    "TSLA": "Automobile and Auto Components", "TESLA": "Automobile and Auto Components",
    "TOYOTA": "Automobile and Auto Components", "TM": "Automobile and Auto Components",
    "JPM": "Financial Services", "JPMORGAN": "Financial Services",
    "GS": "Financial Services", "HSBC": "Financial Services", "CITI": "Financial Services",
    "XOM": "Oil Gas & Consumable Fuels", "EXXON": "Oil Gas & Consumable Fuels",
    "SHELL": "Oil Gas & Consumable Fuels", "BP": "Oil Gas & Consumable Fuels",
    "PFE": "Healthcare", "PFIZER": "Healthcare",
    "KO": "Fast Moving Consumer Goods", "COCA COLA": "Fast Moving Consumer Goods",
    "PG": "Fast Moving Consumer Goods", "UNILEVER": "Fast Moving Consumer Goods",
    "AMZN": "Consumer Services", "AMAZON": "Consumer Services",
}
# Shown when nothing else is close: the largest Nifty 50 names.
BELLWETHERS = ("RELIANCE", "HDFCBANK", "BHARTIARTL", "TCS", "ICICIBANK")

_NAME_NOISE = re.compile(r"\b(LTD|LIMITED|CO|CORP|CORPORATION|COMPANY|THE|OF|AND|INC)\b")


class Status(StrEnum):
    EMPTY = "empty"          # nothing typed
    MATCH = "match"          # exactly one stock: load it
    CHOOSE = "choose"        # several candidates: show a pick list
    NOT_FOUND = "not_found"  # outside the universe: reject and suggest


@dataclass
class SearchResult:
    query: str
    status: Status
    matches: list[Stock] = field(default_factory=list)
    suggestions: list[Stock] = field(default_factory=list)
    message: str = ""

    @property
    def stock(self) -> Stock | None:
        return self.matches[0] if self.status is Status.MATCH else None


def compact(text: str) -> str:
    """Letters and digits only, upper case: 'm&m' -> 'MM', 'Bajaj-Auto.NS' -> 'BAJAJAUTONS'."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def clean_name(text: str) -> str:
    """Upper-case words with legal suffixes and punctuation removed."""
    text = re.sub(r"[^A-Z0-9 ]", " ", text.upper().replace("&", " AND "))
    return " ".join(_NAME_NOISE.sub(" ", text).split())


def _strip_exchange(query: str) -> str:
    return re.sub(r"\.(NS|BO|NSE|BSE)$", "", query.strip(), flags=re.IGNORECASE)


class _Index:
    def __init__(self, universe: tuple[Stock, ...]):
        self.stocks = universe
        self.by_symbol = {compact(s.symbol): s for s in universe}
        self.by_alias: dict[str, list[Stock]] = {}
        for s in universe:
            for a in s.aliases:
                bucket = self.by_alias.setdefault(compact(a), [])
                if s not in bucket:  # 'Tata Motors' and 'TATAMOTORS' compact to the same key
                    bucket.append(s)
        self.by_name = {clean_name(s.name): s for s in universe}
        self.by_group: dict[str, list[Stock]] = {}
        for s in universe:
            if s.group:
                self.by_group.setdefault(compact(s.group), []).append(s)
        # Every searchable string -> stock, for prefix and fuzzy matching.
        self.keys: list[tuple[str, Stock]] = []
        for s in universe:
            for k in (s.symbol, s.name, *s.aliases):
                self.keys.append((clean_name(k), s))

    def word_prefix(self, q: str) -> list[Stock]:
        hits: dict[str, Stock] = {}
        for key, s in self.keys:
            if key.startswith(q) or f" {q}" in f" {key}":
                hits.setdefault(s.symbol, s)
        return list(hits.values())

    def fuzzy(self, q: str, cutoff: float) -> list[Stock]:
        # Whole-string similarity (word order ignored). Partial-match scorers reward any shared
        # substring, which turned 'Coca Cola' into Cholamandalam and 'TSLA' into Tata Steel.
        found = process.extract(q, [k for k, _ in self.keys], scorer=fuzz.token_sort_ratio,
                                score_cutoff=cutoff, limit=40)
        hits: dict[str, Stock] = {}
        for _, _, i in found:
            s = self.keys[i][1]
            hits.setdefault(s.symbol, s)
        return list(hits.values())


_index: _Index | None = None


def _get_index() -> _Index:
    global _index
    if _index is None:
        _index = _Index(stocks())
    return _index


def resolve(query: str) -> SearchResult:
    raw = (query or "").strip()
    if not raw:
        return SearchResult(raw, Status.EMPTY)
    idx = _get_index()
    q_compact = compact(_strip_exchange(raw))
    q_name = clean_name(_strip_exchange(raw))

    def one_or_many(found: list[Stock], why: str) -> SearchResult:
        if len(found) == 1:
            return SearchResult(raw, Status.MATCH, found)
        return SearchResult(raw, Status.CHOOSE, found[:MAX_CHOICES],
                            message=f"{len(found)} Nifty 100 stocks {why} '{raw}'. Pick one.")

    if q_compact in idx.by_symbol:
        return SearchResult(raw, Status.MATCH, [idx.by_symbol[q_compact]])
    if q_compact in idx.by_alias:
        return one_or_many(idx.by_alias[q_compact], "are known as")
    if q_name in idx.by_name:
        return SearchResult(raw, Status.MATCH, [idx.by_name[q_name]])
    if q_compact in idx.by_group:
        return one_or_many(idx.by_group[q_compact], "belong to the group")
    if q_name and len(q_name) >= 3:
        found = idx.word_prefix(q_name)
        if found:
            return one_or_many(found, "match")
    if q_name:
        found = idx.fuzzy(q_name, FUZZY_PICK)
        if found:
            return SearchResult(raw, Status.CHOOSE, found[:MAX_CHOICES],
                                message=f"No exact match for '{raw}'. Did you mean one of these?")
    return SearchResult(raw, Status.NOT_FOUND, suggestions=_suggest(raw, q_name, idx),
                        message=f"'{raw}' is not in the Nifty 100 universe for now.")


def _suggest(raw: str, q_name: str, idx: _Index, n: int = 5) -> list[Stock]:
    sector = GLOBAL_PEERS.get(q_name) or GLOBAL_PEERS.get(compact(_strip_exchange(raw)))
    if sector:
        peers = [s for s in idx.stocks if s.sector == sector]
        if peers:
            return peers[:n]
    if q_name:
        close = idx.fuzzy(q_name, FUZZY_SUGGEST)
        if close:
            return close[:n]
    return [idx.by_symbol[compact(sym)] for sym in BELLWETHERS if compact(sym) in idx.by_symbol]
