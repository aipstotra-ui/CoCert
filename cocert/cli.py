"""CoCert CLI (stdlib argparse — no third-party deps).

    cocert run   --cmd "./game --windowed" [--ping-port 8790]
                 [--scenarios suspend_resume,memory_soak,...] [--out report.json]
                 [--controller-disconnect-cmd "..."] [--controller-reconnect-cmd "..."]
                 [--network-cut-cmd "..."] [--network-restore-cmd "..."]

    cocert demo  --mode clean|crash-on-resume|hang-on-resume|leak|
                        crash-on-event|hang-on-event
                 runs the bundled toy target so you can see a PASS and each
                 failure class without a real game.

Injector command hooks take a '{pid}' placeholder (the game's pid). Both the
disconnect/cut AND the matching reconnect/restore must be given, or the
controller/network scenarios report SKIPPED — never a false PASS.

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


def _hooks_from_args(args) -> dict[str, str]:
    hooks: dict[str, str] = {}
    for key, val in (
        ("controller_disconnect_cmd", args.controller_disconnect_cmd),
        ("controller_reconnect_cmd", args.controller_reconnect_cmd),
        ("network_cut_cmd", args.network_cut_cmd),
        ("network_restore_cmd", args.network_restore_cmd),
    ):
        if val:
            hooks[key] = val
    return hooks


def _cmd_run(args) -> int:
    scenarios = args.scenarios.split(",") if args.scenarios else DEFAULT_SCENARIOS
    adapter = DesktopAdapter(
        shlex.split(args.cmd), ping_port=args.ping_port, hooks=_hooks_from_args(args)
    )
    results = run_suite(adapter, scenarios)
    return _emit(results, args.cmd, args.out)


def _self_cmd(extra: list[str]) -> list[str]:
    """Command to re-invoke this program. Works both from source and from a
    PyInstaller onefile binary (where sys.executable is the binary itself)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    return [sys.executable, "-m", "cocert.cli", *extra]


def _cmd_faultygame(args) -> int:
    # Hidden: launches the bundled toy target so `demo` works from the frozen
    # binary too (can't shell out to `python fixture.py` there).
    from ._fixtures.faultygame import main as fg_main
    return fg_main([
        "--ping-port", str(args.ping_port),
        "--mode", args.mode,
        "--leak-rate-mb-s", str(args.leak_rate_mb_s),
    ]) or 0


def _cmd_demo(args) -> int:
    port = args.ping_port or 8790
    cmd = _self_cmd(["_faultygame", "--ping-port", str(port), "--mode", args.mode])
    # Wire the toy's adverse-event signals as the injector hooks so demo also
    # exercises controller_disconnect and network_loss end to end.
    hooks = {
        "controller_disconnect_cmd": "kill -USR1 {pid}",
        "controller_reconnect_cmd": "kill -USR2 {pid}",
        "network_cut_cmd": "kill -USR1 {pid}",
        "network_restore_cmd": "kill -USR2 {pid}",
    }
    adapter = DesktopAdapter(cmd, ping_port=port, hooks=hooks)
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
    run.add_argument("--controller-disconnect-cmd", default=None,
                     help="shell command to disconnect the controller ({pid} allowed)")
    run.add_argument("--controller-reconnect-cmd", default=None,
                     help="shell command to reconnect the controller ({pid} allowed)")
    run.add_argument("--network-cut-cmd", default=None,
                     help="shell command to cut network ({pid} allowed)")
    run.add_argument("--network-restore-cmd", default=None,
                     help="shell command to restore network ({pid} allowed)")
    run.set_defaults(func=_cmd_run)

    demo = sub.add_parser("demo", help="run against the bundled toy target")
    demo.add_argument("--mode", default="clean",
                      choices=["clean", "crash-on-resume", "hang-on-resume", "leak",
                               "crash-on-event", "hang-on-event"])
    demo.add_argument("--ping-port", type=int, default=None)
    demo.add_argument("--out", default=None)
    demo.set_defaults(func=_cmd_demo)

    fg = sub.add_parser("_faultygame", help=argparse.SUPPRESS)
    fg.add_argument("--ping-port", type=int, required=True)
    fg.add_argument("--mode", default="clean")
    fg.add_argument("--leak-rate-mb-s", type=float, default=8.0)
    fg.set_defaults(func=_cmd_faultygame)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
