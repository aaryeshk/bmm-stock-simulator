"""A small time-to-live cache that works with or without Streamlit running."""
from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable
from typing import Any

FIFTEEN_MINUTES = 15 * 60

_clock: Callable[[], float] = time.monotonic  # replaced in tests


def ttl_cache(seconds: float, *, failure_seconds: float = 0) -> Callable:
    """Cache results per argument tuple for `seconds`.

    Exceptions are cached for `failure_seconds` (0 = not cached), so a down data source is not
    hammered on every Streamlit rerun but is retried soon.
    """
    def decorate(fn: Callable) -> Callable:
        store: dict[tuple, tuple[float, bool, Any]] = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(sorted(kwargs.items())))
            now = _clock()
            with lock:
                hit = store.get(key)
            if hit is not None and hit[0] > now:
                _, ok, value = hit
                if ok:
                    return value
                raise value
            try:
                value = fn(*args, **kwargs)
            except Exception as exc:
                if failure_seconds > 0:
                    with lock:
                        store[key] = (now + failure_seconds, False, exc)
                raise
            with lock:
                store[key] = (now + seconds, True, value)
            return value

        wrapper.cache_clear = store.clear  # type: ignore[attr-defined]
        return wrapper

    return decorate
