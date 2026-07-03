"""Orchestrator — launch the target, run scenarios, collect results.

    launch --> [scenario 1] --> [scenario 2] --> ... --> terminate
                    |                |
                    +----> ScenarioResult (PASS / FAIL / SKIPPED)

Launch failure short-circuits into a single LaunchFailure finding so a bad
target path never masquerades as "all scenarios passed".
"""

from __future__ import annotations

from .adapter import PlatformAdapter
from .desktop_adapter import LaunchFailure
from .models import Finding, FindingType, Outcome, ScenarioResult
from .scenarios import DEFAULT_SCENARIOS, run_scenario


def run_suite(
    adapter: PlatformAdapter,
    scenarios: list[str] | None = None,
    scenario_params: dict[str, dict] | None = None,
) -> list[ScenarioResult]:
    scenarios = scenarios or DEFAULT_SCENARIOS
    scenario_params = scenario_params or {}
    results: list[ScenarioResult] = []

    try:
        adapter.launch()
    except LaunchFailure as exc:
        return [ScenarioResult(
            "launch", Outcome.FAIL,
            [Finding(FindingType.LAUNCH_FAILURE, str(exc))],
        )]

    try:
        for name in scenarios:
            results.append(run_scenario(name, adapter, **scenario_params.get(name, {})))
    finally:
        adapter.terminate()

    return results


def suite_ok(results: list[ScenarioResult]) -> bool:
    """True only if no scenario FAILED. SKIPPED does not fail the suite, but it
    is never counted as a pass either."""
    return all(r.outcome is not Outcome.FAIL for r in results)
