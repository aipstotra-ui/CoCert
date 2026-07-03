"""Monitor — background sampler that records the target's memory over time.

Runs in a daemon thread so a scenario can inject events while the memory
timeseries keeps accruing. The leak check is a least-squares slope over the
samples (bytes/second); no numpy, stdlib only.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .adapter import PlatformAdapter


@dataclass
class MemorySeries:
    samples: list[tuple[float, int]] = field(default_factory=list)  # (elapsed_s, rss_bytes)

    def slope_bytes_per_s(self) -> float:
        """Least-squares slope of rss vs time. 0.0 with fewer than 2 points."""
        n = len(self.samples)
        if n < 2:
            return 0.0
        sx = sum(t for t, _ in self.samples)
        sy = sum(r for _, r in self.samples)
        sxx = sum(t * t for t, _ in self.samples)
        sxy = sum(t * r for t, r in self.samples)
        denom = n * sxx - sx * sx
        if denom == 0:
            return 0.0
        return (n * sxy - sx * sy) / denom

    def growth_bytes(self) -> int:
        if len(self.samples) < 2:
            return 0
        return self.samples[-1][1] - self.samples[0][1]


class MemoryMonitor:
    def __init__(self, adapter: PlatformAdapter, interval: float = 0.25):
        self._adapter = adapter
        self._interval = interval
        self._series = MemorySeries()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            rss = self._adapter.sample_memory_bytes()
            if rss > 0:
                self._series.samples.append((time.monotonic() - self._t0, rss))
            self._stop.wait(self._interval)

    def stop(self) -> MemorySeries:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        return self._series
