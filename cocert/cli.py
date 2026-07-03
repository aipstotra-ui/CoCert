"""CoCert CLI (stdlib argparse — no third-party deps).

    cocert run   --cmd "./game --windowed" [--ping-port 8790]
                 [--scenarios suspend_resume,memory_soak] [--out report.json]

    cocert demo  --mode clean|crash-on-resume|hang-on-resume|leak
                 runs the bundled toy target so you can see a PASS and each
                 failure class without a real game.

Exit code: 0 if certifiable (no FAILs), 1 if any scenario FAILED.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys

from .desktop_adapter import DesktopAdapter
from .orchestrator import run_suite, suite_ok
from .report import build_report, render_text, write_json
from .scenarios import DEFAULT_SCENARIOS

_FIXTURE = os.path.join(os.path.dirname(__file__), "_fixtures", "faultygame.py")


def _emit(results, target, out_path) -> int:
    report = build_report(results, target)
    print(render_text(report))
    if out_path:
        write_json(report, out_path)
        print(f"\nJSON written to {out_path}")
    return 0 if suite_ok(results) else 1


def _cmd_run(args) -> int:
    scenarios = args.scenarios.split(",") if args.scenarios else DEFAULT_SCENARIOS
    adapter = DesktopAdapter(shlex.split(args.cmd), ping_port=args.ping_port)
    results = run_suite(adapter, scenarios)
    return _emit(results, args.cmd, args.out)


def _cmd_demo(args) -> int:
    port = args.ping_port or 8790
    cmd = [sys.executable, _FIXTURE, "--ping-port", str(port), "--mode", args.mode]
    adapter = DesktopAdapter(cmd, ping_port=port)
    results = run_suite(adapter, DEFAULT_SCENARIOS)
    return _emit(results, f"faultygame(--mode {args.mode})", args.out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cocert", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="torture-test a real game build")
    run.add_argument("--cmd", required=True, help="command to launch the game build")
    run.add_argument("--ping-port", type=int, default=None,
                     help="liveness-probe port if the build exposes the SDK hook")
    run.add_argument("--scenarios", default=None, help="comma-separated scenario names")
    run.add_argument("--out", default=None, help="write JSON report to this path")
    run.set_defaults(func=_cmd_run)

    demo = sub.add_parser("demo", help="run against the bundled toy target")
    demo.add_argument("--mode", default="clean",
                      choices=["clean", "crash-on-resume", "hang-on-resume", "leak"])
    demo.add_argument("--ping-port", type=int, default=None)
    demo.add_argument("--out", default=None)
    demo.set_defaults(func=_cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
