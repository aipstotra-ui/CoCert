"""Reporter — JSON (machine) and a plain-text summary (human).

MVP ships JSON + a terminal summary. HTML (Jinja2 timeline + RSS graph) is the
documented fast-follow; it reads the same JSON so nothing here changes.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from .models import Outcome, ScenarioResult


def build_report(results: list[ScenarioResult], target: str) -> dict[str, Any]:
    counts = {o.value: 0 for o in Outcome}
    for r in results:
        counts[r.outcome.value] += 1
    return {
        "tool": "certharness",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "target": target,
        "summary": {
            "total": len(results),
            "passed": counts[Outcome.PASS.value],
            "failed": counts[Outcome.FAIL.value],
            "skipped": counts[Outcome.SKIPPED.value],
            "certifiable": all(r.outcome is not Outcome.FAIL for r in results),
        },
        "scenarios": [r.to_dict() for r in results],
    }


def write_json(report: dict[str, Any], path: str) -> None:
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)


_MARK = {Outcome.PASS.value: "PASS ", Outcome.FAIL.value: "FAIL ", Outcome.SKIPPED.value: "SKIP "}


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"CertHarness report — target: {report['target']}",
        f"generated: {report['generated_at']}",
        "-" * 60,
    ]
    for sc in report["scenarios"]:
        lines.append(f"[{_MARK.get(sc['outcome'], '?    ')}] {sc['name']}")
        for f in sc["findings"]:
            lines.append(f"        - {f['type']}: {f['message']}")
        if sc.get("details"):
            lines.append(f"        details: {sc['details']}")
    s = report["summary"]
    lines.append("-" * 60)
    lines.append(
        f"total={s['total']} passed={s['passed']} failed={s['failed']} skipped={s['skipped']}"
    )
    if s["certifiable"]:
        verdict = "CERTIFIABLE (no failures)"
        if s["skipped"]:
            # Honest: skipped categories were NOT verified — don't imply they passed.
            verdict += f" — but {s['skipped']} scenario(s) SKIPPED (not verified)"
    else:
        verdict = "NOT CERTIFIABLE (failures present)"
    lines.append("VERDICT: " + verdict)
    return "\n".join(lines)
