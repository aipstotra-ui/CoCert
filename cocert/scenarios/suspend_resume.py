"""suspend_resume scenario — the console 'sleep/wake' torture test.

This is the single most-failed cert category. One cycle:
  1. confirm the game is responsive (baseline), note its reported state
  2. suspend it (freeze all threads, like closing the console lid)
  3. hold it suspended (optionally a randomized hold within a range)
  4. resume it
  5. poll for responsiveness within a grace window

Why cycles + randomized holds matter on a REAL game: cert failures are
state-specific (fine at the menu, corrupts a save if suspended mid-save).
One injection at one arbitrary moment is a demo. N cycles at randomized
intervals across a live session is coverage — and the recorded game state
tells triage WHERE it broke.

Outcomes (every failure named):
  - PASS            : all cycles recovered within grace
  - GameCrash       : process died on/after a resume
  - RecoveryTimeout : alive but never responsive again within grace
  - GameHang        : not responsive before we even injected

The resume ALWAYS runs (finally), so we never leave a process frozen.
"""

from __future__ import annotations

import random
import time

from ..adapter import PlatformAdapter
from ..models import Finding, FindingType, Outcome, ScenarioResult

NAME = "suspend_resume"


def _fail(details: dict, cycle: int, state: str | None, ftype: FindingType,
          msg: str) -> ScenarioResult:
    where = f" (cycle {cycle}" + (f", game state: {state})" if state else ")")
    details["failed_cycle"] = cycle
    if state:
        details["state_at_failure"] = state
    return ScenarioResult(NAME, Outcome.FAIL, [Finding(ftype, msg + where)], details)


def run(
    adapter: PlatformAdapter,
    hold_s: float = 1.5,
    grace_s: float = 5.0,
    probe_timeout: float = 1.0,
    cycles: int = 1,
    hold_jitter_s: float = 0.0,
    gap_s: float = 0.3,
) -> ScenarioResult:
    """cycles: how many suspend/resume rounds to run (soak-style torture).
    hold_jitter_s: adds random(0..jitter) to each hold so injections land at
    different moments of the game's life. gap_s: pause between cycles."""
    details: dict = {
        "hold_s": hold_s, "grace_s": grace_s,
        "cycles_requested": cycles, "hold_jitter_s": hold_jitter_s,
    }
    states_seen: list[str] = []

    for cycle in range(1, cycles + 1):
        state = adapter.probe_state(probe_timeout)
        if state:
            states_seen.append(state)
            details["states_seen"] = sorted(set(states_seen))

        if not adapter.is_responsive(probe_timeout):
            return _fail(details, cycle, state, FindingType.GAME_HANG,
                         "target was not responsive before suspend")

        hold = hold_s + (random.uniform(0.0, hold_jitter_s) if hold_jitter_s else 0.0)
        suspended = False
        try:
            adapter.suspend()
            suspended = True
            time.sleep(hold)
        finally:
            if suspended:
                adapter.resume()

        # Give the OS a beat to actually deliver SIGCONT and reschedule threads.
        time.sleep(0.2)

        if not adapter.is_alive():
            return _fail(details, cycle, state, FindingType.GAME_CRASH,
                         "target exited on resume from suspend (classic sleep/wake cert fail)")

        recovered = False
        deadline = time.monotonic() + grace_s
        while time.monotonic() < deadline:
            if adapter.is_responsive(probe_timeout):
                recovered = True
                break
            if not adapter.is_alive():
                return _fail(details, cycle, state, FindingType.GAME_CRASH,
                             "target crashed during recovery window")
            time.sleep(0.25)

        if not recovered:
            return _fail(details, cycle, state, FindingType.RECOVERY_TIMEOUT,
                         f"alive but not responsive within {grace_s}s after resume")

        details["cycles_completed"] = cycle
        if cycle < cycles:
            time.sleep(gap_s)

    details["recovered"] = True
    return ScenarioResult(NAME, Outcome.PASS, [], details)
