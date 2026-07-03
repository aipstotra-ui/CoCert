"""network_loss scenario — drop the network, expect no crash/hang.

Another cert staple: kill connectivity mid-session (matchmaking, cloud saves,
online checks) and confirm the title degrades gracefully and recovers when the
network returns. The cut mechanism is host-/rig-specific, so DesktopAdapter
runs a tester-supplied command hook; with no hook this is reported SKIPPED.
"""

from __future__ import annotations

from ..adapter import PlatformAdapter
from ..models import ScenarioResult
from ._event import run_event

NAME = "network_loss"


def run(adapter: PlatformAdapter, grace_s: float = 4.0) -> ScenarioResult:
    return run_event(
        adapter,
        NAME,
        inject=adapter.cut_network,
        restore=adapter.restore_network,
        grace_s=grace_s,
    )
