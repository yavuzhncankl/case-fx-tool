"""A small in-process cache so the same question is not asked twice.

Two lifetimes, because the two kinds of answer age differently:

* a rate for a date in the past is final once published — cache it for a day;
* "the latest rate" changes when the ECB publishes around 16:00 CET — cache it
  for minutes, so a request made after publication does not keep serving the
  previous day's number.

Nothing negative is cached: a failure is a bad moment, not a fact.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable, Generic, Hashable, TypeVar

V = TypeVar("V")

TTL_HISTORIC_SECONDS = 24 * 60 * 60
TTL_LATEST_SECONDS = 10 * 60


class TTLCache(Generic[V]):
    def __init__(
        self,
        maxsize: int = 512,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._entries: OrderedDict[Hashable, tuple[float, V]] = OrderedDict()
        self._maxsize = maxsize
        self._clock = clock

    def get(self, key: Hashable) -> V | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def set(self, key: Hashable, value: V, ttl_seconds: float) -> None:
        self._entries[key] = (self._clock() + ttl_seconds, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
