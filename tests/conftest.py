import os

import pytest

# Tests never touch the network unless BMM_LIVE=1 (see tests/test_live.py).
if not os.environ.get("BMM_LIVE"):
    os.environ["BMM_OFFLINE"] = "1"


@pytest.fixture(autouse=True)
def clear_caches():
    from bmm import data, news

    data._yahoo_cached.cache_clear()
    news.get_headlines.cache_clear()
    yield
