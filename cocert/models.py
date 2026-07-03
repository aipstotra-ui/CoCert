"""Result and finding data types shared across the harness.

A run produces one ScenarioResult per scenario. Each result has an Outcome
(PASS / FAIL / SKIPPED) and zero or more Findings. Every failure has a NAME
(FindingType) — the harness never reports a bare "it broke", and it never
reports PASS when a scenario could not actually run (that is SKIPPED).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from typing import Any


class Outcome(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"  # injector unavailable / precondition not met — never a silent PASS


class FindingType(str, enum.Enum):
    LAUNCH_FAILURE = "LaunchFailure"      # target didn't start
    GAME_CRASH = "GameCrash"              # process exited unexpectedly
    GAME_HANG = "GameHang"                # alive but unresponsive
    MEMORY_LEAK = "MemoryLeak"            # RSS slope over threshold on a soak
    RECOVERY_TIMEOUT = "RecoveryTimeout"  # never returned to responsive after resume/reconnect
    INJECTOR_UNAVAILABLE = "InjectorUnavailable"  # could not run here (perms/host) -> SKIPPED


@dataclass
class Finding:
    type: FindingType
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "message": self.message}


@dataclass
class ScenarioResult:
    name: str
    outcome: Outcome
    findings: list[Finding] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "outcome": self.outcome.value,
            "findings": [f.to_dict() for f in self.findings],
            "details": self.details,
        }

    @property
    def passed(self) -> bool:
        return self.outcome is Outcome.PASS


def result_skipped(name: str, reason: str) -> ScenarioResult:
    return ScenarioResult(
        name=name,
        outcome=Outcome.SKIPPED,
        findings=[Finding(FindingType.INJECTOR_UNAVAILABLE, reason)],
    )
