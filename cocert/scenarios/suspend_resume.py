"""suspend_resume scenario — the console 'sleep/wake' torture test.

This is the single most-failed cert category. We:
  1. confirm the game is responsive (baseline)
  2. suspend it (freeze all threads, like closing the console lid)
  3. hold it suspended
  4. resume it
  5. poll for responsiveness within a grace window

Outcomes (every failure named):
  - PASS            : regained responsiveness within grace
  - GameCrash       : process died on/after resume
  - RecoveryTimeout : alive but never responsive again within grace
  - GameHang        : alive, not responsive, and not making progress

The resume ALWAYS runs (finally), so we never leave a process frozen.
"""

from __future__ import annotations

import time

from ..adapter import PlatformAdapter
from ..models import Finding, FindingType, Outcome, ScenarioResult

NAME = "suspend_resume"


def run(
    adapter: PlatformAdapter,
    hold_s: float = 1.5,
    grace_s: float = 5.0,
    probe_timeout: float = 1.0,
) -> ScenarioResult:
    details: dict = {"hold_s": hold_s, "grace_s": grace_s}

    if not adapter.is_responsive(probe_timeout):
        return ScenarioResult(
            NAME, Outcome.FAIL,
            [Finding(FindingType.GAME_HANG, "target was not responsive before suspend")],
            details,
        )

    suspended = False
    try:
        adapter.suspend()
        suspended = True
        details["responsive_while_suspended"] = adapter.is_responsive(probe_timeout)
        time.sleep(hold_s)
    finally:
        if suspended:
            adapter.resume()

    # Give the OS a beat to actually deliver SIGCONT and reschedule threads.
    time.sleep(0.2)

    if not adapter.is_alive():
        return ScenarioResult(
            NAME, Outcome.FAIL,
            [Finding(FindingType.GAME_CRASH,
                     "target exited on resume from suspend (classic sleep/wake cert fail)")],
            details,
        )

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if adapter.is_responsive(probe_timeout):
            details["recovered"] = True
            return ScenarioResult(NAME, Outcome.PASS, [], details)
        if not adapter.is_alive():
            return ScenarioResult(
                NAME, Outcome.FAIL,
                [Finding(FindingType.GAME_CRASH, "target crashed during recovery window")],
                details,
            )
        time.sleep(0.25)

    details["recovered"] = False
    return ScenarioResult(
        NAME, Outcome.FAIL,
        [Finding(FindingType.RECOVERY_TIMEOUT,
                 f"alive but not responsive within {grace_s}s after resume")],
        details,
    )
