import pandas as pd

from bmm import news
from bmm.news import Headline, google_query, merge, parse_google_rss, parse_yahoo_news

NOW = pd.Timestamp("2026-10-04 08:00", tz="UTC")

GOOGLE_XML = """<?xml version="1.0"?><rss><channel>
<item><title>Reliance shares rise on retail push - Economic Times</title>
  <link>https://news.google.com/a</link><pubDate>Fri, 03 Oct 2026 10:00:00 GMT</pubDate>
  <source url="https://economictimes.com">Economic Times</source></item>
<item><title>Old story - Mint</title><link>https://news.google.com/b</link>
  <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate><source url="https://livemint.com">Mint</source></item>
<item><title>No date</title><link>x</link></item>
</channel></rss>"""


def test_google_rss_strips_publisher_suffix():
    items = parse_google_rss(GOOGLE_XML)
    assert len(items) == 2
    assert items[0].title == "Reliance shares rise on retail push"
    assert items[0].publisher == "Economic Times"
    assert items[0].published == pd.Timestamp("2026-10-03 10:00", tz="UTC")


def test_yahoo_new_nested_format():
    items = parse_yahoo_news([{"id": "1", "content": {
        "title": "RIL Q2 preview", "pubDate": "2026-10-02T05:30:00Z",
        "provider": {"displayName": "Reuters"},
        "canonicalUrl": {"url": "https://finance.yahoo.com/x"}}}])
    assert items == [Headline("RIL Q2 preview", "Reuters", "https://finance.yahoo.com/x",
                              pd.Timestamp("2026-10-02 05:30", tz="UTC"), "yahoo")]


def test_yahoo_old_flat_format():
    items = parse_yahoo_news([{"title": "Old format", "publisher": "PTI", "link": "u",
                               "providerPublishTime": 1790000000}])
    assert items[0].publisher == "PTI"
    assert items[0].published == pd.Timestamp(1790000000, unit="s", tz="UTC")


def test_yahoo_skips_items_without_title_or_date():
    assert parse_yahoo_news([{"content": {"title": ""}}, {"content": {"title": "x"}}]) == []
    assert parse_yahoo_news(None) == []


def h(title, days_ago, source="google"):
    return Headline(title, "P", "u", NOW - pd.Timedelta(days=days_ago), source)


def test_merge_dedupes_sorts_and_drops_old():
    out = merge([[h("Reliance up 2%", 1, "yahoo"), h("Old", 30)],
                 [h("Reliance up 2% ", 2), h("Newest", 0.1)]], NOW)
    assert [x.title for x in out] == ["Newest", "Reliance up 2%"]
    assert out[1].source == "yahoo"  # the more recent copy wins


def test_merge_limits_count():
    assert len(merge([[h(f"t{i}", i / 10) for i in range(50)]], NOW, limit=20)) == 20


def test_google_query_uses_short_name():
    assert google_query("Reliance Industries Ltd").startswith('"Reliance Industries" ')


def test_offline_headlines_say_so():
    result = news.get_headlines("RELIANCE.NS", "Reliance Industries Ltd")
    assert result.headlines == () and "offline" in result.notes[0]


def test_one_source_failing_still_returns_the_other(monkeypatch):
    monkeypatch.setattr(news, "offline", lambda: False)
    monkeypatch.setattr(news, "fetch_yahoo_news", lambda s: (_ for _ in ()).throw(TimeoutError()))
    fresh = Headline("Fresh", "ET", "u", pd.Timestamp.now(tz="UTC"), "google")
    monkeypatch.setattr(news, "fetch_google_news", lambda name: [fresh])
    result = news.get_headlines("RELIANCE.NS", "Reliance Industries Ltd")
    assert [x.title for x in result.headlines] == ["Fresh"]
    assert result.notes == ("Yahoo Finance headlines unavailable (TimeoutError).",)


def test_both_sources_failing_is_not_an_error(monkeypatch):
    monkeypatch.setattr(news, "offline", lambda: False)
    boom = lambda arg: (_ for _ in ()).throw(ConnectionError())  # noqa: E731
    monkeypatch.setattr(news, "fetch_yahoo_news", boom)
    monkeypatch.setattr(news, "fetch_google_news", boom)
    result = news.get_headlines("TCS.NS", "Tata Consultancy Services Ltd")
    assert result.headlines == ()
    assert len(result.notes) == 3 and "No headlines" in result.notes[-1]
