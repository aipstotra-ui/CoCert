"""Built-in scenario registry.

Each scenario exposes NAME and run(adapter, **params) -> ScenarioResult.
Best-effort injectors (controller/network) that the DesktopAdapter can't do on
a given host raise InjectorUnavailable and are reported as SKIPPED, never PASS.
"""

from __future__ import annotations

from ..adapter import InjectorUnavailable, PlatformAdapter
from ..models import ScenarioResult, result_skipped
from . import memory_soak, suspend_resume

REGISTRY = {
    suspend_resume.NAME: suspend_resume.run,
    memory_soak.NAME: memory_soak.run,
}

DEFAULT_SCENARIOS = [suspend_resume.NAME, memory_soak.NAME]


def run_scenario(name: str, adapter: PlatformAdapter, **params) -> ScenarioResult:
    if name not in REGISTRY:
        raise KeyError(f"unknown scenario: {name}")
    try:
        return REGISTRY[name](adapter, **params)
    except InjectorUnavailable as exc:
        return result_skipped(name, str(exc))
