# CoCert (MVP)

A platform-state torture harness for game builds. Point it at a **desktop build**
of your game; it drives the game through the console-certification failure
scenarios that don't require playing well, and detects crash / hang / memory-leak
/ failed-recovery with named findings and a pass/fail report.

This is the wedge from the design doc: the most-failed cert categories
(sleep/resume, controller disconnect, network loss, long-session memory) are
**system-state perturbations**, not gameplay — so no game-playing AI is needed.
Console (Sony/MS/Nintendo) devkit support is deferred behind `PlatformAdapter`.

## Status: MVP vertical slice

Implemented and tested:
- `PlatformAdapter` seam + `DesktopAdapter` (stdlib only — no pip installs).
- suspend/resume via SIGSTOP/SIGCONT across the process **tree** (handles
  launcher-wrapped games).
- Liveness probe via an optional local socket "ping/pong" hook.
- Background memory monitor + least-squares leak detection.
- Scenarios: `suspend_resume`, `memory_soak`.
- Named findings: LaunchFailure, GameCrash, GameHang, MemoryLeak,
  RecoveryTimeout, InjectorUnavailable (SKIPPED — never a silent PASS).
- A shipped toy target (`fixtures/faultygame.py`) so detection is testable
  without a real game. 10 passing tests.

Deferred (documented, not silently dropped): controller-disconnect + network-loss
injectors (best-effort, need privileges), HTML report, PyInstaller single-binary
distribution + CI, and the console adapters.

## Try it (zero dependencies, needs Python 3.9+ on macOS/Linux)

From source:

```bash
python3 -m cocert.cli demo --mode clean            # -> CERTIFIABLE, exit 0
python3 -m cocert.cli demo --mode crash-on-resume  # -> GameCrash
python3 -m cocert.cli demo --mode hang-on-resume   # -> RecoveryTimeout
python3 -m cocert.cli demo --mode leak             # -> MemoryLeak
```

Or install it and use the `cocert` command:

```bash
pip install .
cocert demo --mode clean
```

Run against a real build that exposes the liveness hook:

```bash
cocert run --cmd "./MyGame --windowed" --ping-port 8790 --out report.json
```

Exit code is 0 when certifiable (no failures), 1 when any scenario fails — wire
it straight into CI.

## The optional 5-line SDK hook

Responsiveness is exact when the build answers a TCP "ping" with "pong" on a
local port (see `cocert/_fixtures/faultygame.py`). Without it, `is_responsive()`
falls back to "process alive" — a heuristic. Offering studios this tiny opt-in
integration is the v2 accuracy upgrade.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Layout

```
cocert/
  adapter.py             PlatformAdapter ABC (the console-vs-desktop seam)
  desktop_adapter.py     DesktopAdapter: launch/suspend/resume/probe/memory (stdlib)
  monitor.py             background RSS sampler + slope math
  models.py              Outcome / FindingType / ScenarioResult
  scenarios/             suspend_resume, memory_soak, registry
  orchestrator.py        launch -> run scenarios -> terminate
  report.py              JSON + text report
  cli.py                 `run` and `demo` commands
  _fixtures/faultygame.py toy target with selectable defects (ships for `demo`)
tests/                   unittest suite (10 tests)
pyproject.toml           packaging; `pip install .` -> `cocert` command
.github/workflows/ci.yml runs tests on ubuntu + macos, py3.9 & 3.12
```
