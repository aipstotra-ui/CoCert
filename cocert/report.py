"""Reporter — JSON (machine), plain-text summary, and standalone HTML.

The HTML report is a single self-contained file (inline CSS, inline SVG chart,
no external assets) so a tester can email or Slack it to anyone — it renders
identically offline. It reads the same report dict as the JSON output.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
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


# --- standalone HTML report ---

_SCENARIO_TITLES = {
    "suspend_resume": "Suspend / Resume",
    "memory_soak": "Memory Soak",
    "controller_disconnect": "Controller Disconnect",
    "network_loss": "Network Loss",
    "launch": "Launch",
}

_BADGE = {
    "PASS": ("PASS", "#12b76a"),
    "FAIL": ("FAIL", "#f04438"),
    "SKIPPED": ("SKIPPED", "#f79009"),
}


def _esc(v: Any) -> str:
    return _html.escape(str(v))


def _rss_svg(series: list) -> str:
    """Inline SVG line chart of (t_seconds, rss_mb) points. No JS needed."""
    if len(series) < 2:
        return ""
    w, h, pad = 640, 160, 28
    ts = [p[0] for p in series]
    ys = [p[1] for p in series]
    t0, t1 = min(ts), max(ts)
    y0, y1 = min(ys), max(ys)
    tspan = (t1 - t0) or 1.0
    yspan = (y1 - y0) or 1.0
    pts = " ".join(
        f"{pad + (t - t0) / tspan * (w - 2 * pad):.1f},"
        f"{h - pad - (y - y0) / yspan * (h - 2 * pad):.1f}"
        for t, y in series
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Memory over time">'
        f'<rect width="{w}" height="{h}" fill="#0d1117" rx="8"/>'
        f'<polyline points="{pts}" fill="none" stroke="#4c9aff" stroke-width="2"/>'
        f'<text x="{pad}" y="16" fill="#8b949e" font-size="11">RSS memory (MB)</text>'
        f'<text x="{pad}" y="{h - 8}" fill="#8b949e" font-size="11">{y0:.0f}–{y1:.0f} MB '
        f'over {t1 - t0:.0f}s</text></svg>'
    )


def render_html(report: dict[str, Any]) -> str:
    s = report["summary"]
    if s["certifiable"] and not s["skipped"]:
        vtext, vcolor = "CERTIFIABLE — no failures", "#12b76a"
    elif s["certifiable"]:
        vtext = f"NO FAILURES — but {s['skipped']} scenario(s) skipped (not verified)"
        vcolor = "#f79009"
    else:
        vtext, vcolor = "NOT CERTIFIABLE — failures present", "#f04438"

    cards = []
    for sc in report["scenarios"]:
        label, color = _BADGE.get(sc["outcome"], ("?", "#8b949e"))
        title = _SCENARIO_TITLES.get(sc["name"], sc["name"])
        rows = "".join(
            f'<div class="finding"><span class="ftype">{_esc(f["type"])}</span> '
            f'{_esc(f["message"])}</div>'
            for f in sc["findings"]
        )
        d = sc.get("details") or {}
        chips = []
        if "cycles_completed" in d:
            chips.append(f'{d["cycles_completed"]}/{d.get("cycles_requested", "?")} cycles')
        if "states_seen" in d:
            chips.append("states: " + ", ".join(d["states_seen"]))
        if "state_at_injection" in d:
            chips.append(f'injected during: {d["state_at_injection"]}')
        if "state_at_failure" in d:
            chips.append(f'failed during: {d["state_at_failure"]}')
        if "growth_bytes" in d:
            chips.append(f'memory growth: {d["growth_bytes"] / 1e6:.1f} MB '
                         f'over {d.get("duration_s", "?")}s')
        chip_html = "".join(f'<span class="chip">{_esc(c)}</span>' for c in chips)
        chart = _rss_svg(d.get("rss_series_mb", [])) if sc["name"] == "memory_soak" else ""
        cards.append(
            f'<div class="card"><div class="card-head"><h3>{_esc(title)}</h3>'
            f'<span class="badge" style="background:{color}">{label}</span></div>'
            f'{chip_html}{rows}{chart}</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CoCert report — {_esc(report["target"])}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ font: 15px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
         background: #010409; color: #e6edf3; padding: 40px 20px; }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  h1 {{ font-size: 22px; letter-spacing: -0.3px; }}
  .sub {{ color: #8b949e; font-size: 13px; margin: 4px 0 24px; }}
  .verdict {{ padding: 14px 18px; border-radius: 10px; font-weight: 600;
              background: {vcolor}22; border: 1px solid {vcolor}; color: {vcolor};
              margin-bottom: 24px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat {{ background: #0d1117; border: 1px solid #21262d; border-radius: 10px;
           padding: 10px 18px; text-align: center; min-width: 90px; }}
  .stat b {{ display: block; font-size: 22px; }}
  .stat span {{ color: #8b949e; font-size: 12px; }}
  .card {{ background: #0d1117; border: 1px solid #21262d; border-radius: 10px;
           padding: 18px; margin-bottom: 14px; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: center;
                margin-bottom: 8px; }}
  .card h3 {{ font-size: 16px; }}
  .badge {{ color: #fff; font-size: 12px; font-weight: 700; padding: 3px 10px;
            border-radius: 999px; }}
  .chip {{ display: inline-block; background: #161b22; border: 1px solid #30363d;
           color: #8b949e; font-size: 12px; border-radius: 999px;
           padding: 2px 10px; margin: 2px 6px 8px 0; }}
  .finding {{ background: #f0443815; border-left: 3px solid #f04438;
              padding: 8px 12px; border-radius: 6px; margin: 8px 0; font-size: 14px; }}
  .ftype {{ font-weight: 700; color: #ff7b72; }}
  svg {{ width: 100%; height: auto; margin-top: 10px; }}
  footer {{ color: #484f58; font-size: 12px; margin-top: 28px; text-align: center; }}
</style></head><body><div class="wrap">
<h1>CoCert pre-certification report</h1>
<div class="sub">target: {_esc(report["target"])} &middot; generated {_esc(report["generated_at"])}</div>
<div class="verdict">{_esc(vtext)}</div>
<div class="stats">
  <div class="stat"><b>{s["total"]}</b><span>scenarios</span></div>
  <div class="stat"><b style="color:#12b76a">{s["passed"]}</b><span>passed</span></div>
  <div class="stat"><b style="color:#f04438">{s["failed"]}</b><span>failed</span></div>
  <div class="stat"><b style="color:#f79009">{s["skipped"]}</b><span>skipped</span></div>
</div>
{"".join(cards)}
<footer>Generated by CoCert — platform-state torture harness for game builds</footer>
</div></body></html>"""


def write_html(report: dict[str, Any], path: str) -> None:
    with open(path, "w") as fh:
        fh.write(render_html(report))
