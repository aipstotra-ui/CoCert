"""memory_soak scenario — long-session memory-leak detection.

Run the game for a while under the background MemoryMonitor and check the RSS
trend. A slow upward slope over a long play session is a common cert reject
("memory grows unbounded"). We flag MemoryLeak when BOTH the slope and the
absolute growth exceed thresholds, so normal warm-up allocation doesn't trip it.
"""

from __future__ import annotations

import time

from ..adapter import PlatformAdapter
from ..models import Finding, FindingType, Outcome, ScenarioResult
from ..monitor import MemoryMonitor

NAME = "memory_soak"


def run(
    adapter: PlatformAdapter,
    duration_s: float = 4.0,
    interval_s: float = 0.25,
    slope_threshold_bps: float = 1_000_000.0,  # 1 MB/s sustained
    min_growth_bytes: int = 15_000_000,         # and at least ~15 MB total
) -> ScenarioResult:
    if not adapter.is_alive():
        return ScenarioResult(
            NAME, Outcome.FAIL,
            [Finding(FindingType.GAME_CRASH, "target not alive at soak start")],
        )

    mon = MemoryMonitor(adapter, interval=interval_s)
    mon.start()
    time.sleep(duration_s)
    series = mon.stop()

    slope = series.slope_bytes_per_s()
    growth = series.growth_bytes()
    # Downsample the RSS timeseries to <=120 points for the HTML report chart:
    # a 24h soak at 0.25s intervals is 345k samples — the trend is what matters.
    samples = series.samples
    step = max(1, len(samples) // 120)
    chart = [(round(t, 2), round(r / 1e6, 2)) for t, r in samples[::step]]
    details = {
        "samples": len(samples),
        "slope_bytes_per_s": round(slope, 1),
        "growth_bytes": growth,
        "duration_s": duration_s,
        "rss_series_mb": chart,
    }

    if not adapter.is_alive():
        return ScenarioResult(
            NAME, Outcome.FAIL,
            [Finding(FindingType.GAME_CRASH, "target crashed during soak")],
            details,
        )

    if slope >= slope_threshold_bps and growth >= min_growth_bytes:
        return ScenarioResult(
            NAME, Outcome.FAIL,
            [Finding(FindingType.MEMORY_LEAK,
                     f"RSS grew ~{growth/1e6:.1f} MB at ~{slope/1e6:.2f} MB/s over {duration_s}s")],
            details,
        )

    return ScenarioResult(NAME, Outcome.PASS, [], details)
