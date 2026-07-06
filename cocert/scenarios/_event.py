"""Shared 'adverse platform event' scenario.

Controller-disconnect and network-loss are the same shape: the game is running
fine, an external event happens, and we check the game handles it and recovers
when the event clears. Only the inject/restore actions differ, so both
scenarios delegate here.

    baseline responsive? -> inject event -> still alive? -> restore -> recovers?

The inject action may raise InjectorUnavailable (no hook configured for this
host); the scenario registry turns that into SKIPPED, never PASS. Restore is
always attempted in a `finally` so we never leave the game in the injected
state.
"""

from __future__ import annotations

import time
from typing import Callable

from ..adapter import PlatformAdapter
from ..models import Finding, FindingType, Outcome, ScenarioResult


def run_event(
    adapter: PlatformAdapter,
    name: str,
    inject: Callable[[], None],
    restore: Callable[[], None],
    settle_s: float = 0.4,
    grace_s: float = 4.0,
    probe_timeout: float = 1.0,
) -> ScenarioResult:
    details: dict = {"grace_s": grace_s}

    state = adapter.probe_state(probe_timeout)
    if state:
        details["state_at_injection"] = state

    if not adapter.is_responsive(probe_timeout):
        return ScenarioResult(
            name, Outcome.FAIL,
            [Finding(FindingType.GAME_HANG, "target was not responsive before the event")],
            details,
        )

    injected = False
    try:
        inject()  # may raise InjectorUnavailable -> SKIPPED at the registry
        injected = True
        time.sleep(settle_s)

        if not adapter.is_alive():
            return ScenarioResult(
                name, Outcome.FAIL,
                [Finding(FindingType.GAME_CRASH,
                         f"target crashed when the {name} event was injected")],
                details,
            )
    finally:
        if injected:
            try:
                restore()
            except Exception:  # noqa: BLE001 — best-effort recovery
                pass

    time.sleep(0.2)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if adapter.is_responsive(probe_timeout):
            details["recovered"] = True
            return ScenarioResult(name, Outcome.PASS, [], details)
        if not adapter.is_alive():
            return ScenarioResult(
                name, Outcome.FAIL,
                [Finding(FindingType.GAME_CRASH, f"target crashed recovering from {name}")],
                details,
            )
        time.sleep(0.25)

    details["recovered"] = False
    return ScenarioResult(
        name, Outcome.FAIL,
        [Finding(FindingType.RECOVERY_TIMEOUT,
                 f"alive but not responsive within {grace_s}s after {name} restored")],
        details,
    )
