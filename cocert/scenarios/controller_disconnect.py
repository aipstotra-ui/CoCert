"""controller_disconnect scenario — yank the controller, expect graceful handling.

A cert staple: disconnect the active controller mid-play; the title must pause
or show a reconnect prompt and recover cleanly when the pad comes back. The
actual disconnect is rig-specific, so DesktopAdapter runs a tester-supplied
command hook; with no hook this is reported SKIPPED, not PASS.
"""

from __future__ import annotations

from ..adapter import PlatformAdapter
from ..models import ScenarioResult
from ._event import run_event

NAME = "controller_disconnect"


def run(adapter: PlatformAdapter, grace_s: float = 4.0) -> ScenarioResult:
    return run_event(
        adapter,
        NAME,
        inject=adapter.disconnect_controller,
        restore=adapter.reconnect_controller,
        grace_s=grace_s,
    )
