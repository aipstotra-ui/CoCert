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
    progress=None,
) -> list[ScenarioResult]:
    """progress: optional callable(event: str, payload: dict) fired at
    launch / scenario_start / scenario_end / done — lets a UI show live
    status without the engine knowing anything about UIs."""
    scenarios = scenarios or DEFAULT_SCENARIOS
    scenario_params = scenario_params or {}
    results: list[ScenarioResult] = []

    def emit(event: str, **payload) -> None:
        if progress is not None:
            try:
                progress(event, payload)
            except Exception:  # noqa: BLE001 — UI bugs must never kill a run
                pass

    emit("launch", scenarios=scenarios)
    try:
        adapter.launch()
    except LaunchFailure as exc:
        result = ScenarioResult(
            "launch", Outcome.FAIL,
            [Finding(FindingType.LAUNCH_FAILURE, str(exc))],
        )
        emit("done", ok=False)
        return [result]

    try:
        for name in scenarios:
            emit("scenario_start", name=name)
            result = run_scenario(name, adapter, **scenario_params.get(name, {}))
            results.append(result)
            emit("scenario_end", name=name, outcome=result.outcome.value)
    finally:
        adapter.terminate()

    emit("done", ok=suite_ok(results))
    return results


def suite_ok(results: list[ScenarioResult]) -> bool:
    """True only if no scenario FAILED. SKIPPED does not fail the suite, but it
    is never counted as a pass either."""
    return all(r.outcome is not Outcome.FAIL for r in results)
