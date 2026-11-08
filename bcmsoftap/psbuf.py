"""Hold frames for a phone in power save until it is awake again.

A phone sets the PM bit when it dozes or leaves the channel to scan (iOS does
that many times a second right after joining). A real access point buffers
frames for it meanwhile; without that, the replies to its first requests were
lost and iOS left the hotspot again (box log 2026-11-08)."""
from collections import deque
from typing import Callable, Hashable


class PsBuffer:
    def __init__(self, tx: Callable[[Hashable, object], None], limit: int = 64):
        self._tx, self._limit = tx, limit
        self._sleeping: set = set()
        self._held: dict = {}

    def send(self, sta, frame) -> None:
        if sta in self._sleeping:
            self._held.setdefault(sta, deque(maxlen=self._limit)).append(frame)
        else:
            self._tx(sta, frame)

    def power(self, sta, sleeping: bool) -> None:
        if sleeping:
            self._sleeping.add(sta)
            return
        self._sleeping.discard(sta)
        q = self._held.pop(sta, None)
        while q:
            self._tx(sta, q.popleft())

    def ps_poll(self, sta) -> None:
        q = self._held.get(sta)
        if q:
            self._tx(sta, q.popleft())

    def forget(self, sta) -> None:
        self._sleeping.discard(sta)
        self._held.pop(sta, None)
