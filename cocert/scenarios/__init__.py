"""Built-in scenario registry.

Each scenario exposes NAME and run(adapter, **params) -> ScenarioResult.
Best-effort injectors (controller/network) that the DesktopAdapter can't do on
a given host raise InjectorUnavailable and are reported as SKIPPED, never PASS.
"""

from __future__ import annotations

from ..adapter import InjectorUnavailable, PlatformAdapter
from ..models import ScenarioResult, result_skipped
from . import controller_disconnect, memory_soak, network_loss, suspend_resume

REGISTRY = {
    suspend_resume.NAME: suspend_resume.run,
    memory_soak.NAME: memory_soak.run,
    controller_disconnect.NAME: controller_disconnect.run,
    network_loss.NAME: network_loss.run,
}

# Run everything by default. Controller/network SKIP cleanly when no injector
# hook is configured, so a bare `cocert run --cmd ...` shows exactly which cert
# categories were actually exercised vs skipped — never a false PASS.
DEFAULT_SCENARIOS = [
    suspend_resume.NAME,
    memory_soak.NAME,
    controller_disconnect.NAME,
    network_loss.NAME,
]


def run_scenario(name: str, adapter: PlatformAdapter, **params) -> ScenarioResult:
    if name not in REGISTRY:
        raise KeyError(f"unknown scenario: {name}")
    try:
        return REGISTRY[name](adapter, **params)
    except InjectorUnavailable as exc:
        return result_skipped(name, str(exc))
