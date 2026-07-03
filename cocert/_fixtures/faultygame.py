#!/usr/bin/env python3
"""faultygame — a toy 'game' with selectable defects, for testing CoCert.

It exposes the optional SDK liveness hook (a TCP socket that answers b"ping"
with b"pong") so the harness can measure responsiveness exactly, then behaves
badly on demand:

  --mode clean            behaves; survives every scenario
  --mode crash-on-resume  exits(1) when woken from suspend   (catches SIGCONT)
  --mode hang-on-resume   stops answering pings after resume  (SIGCONT)
  --mode leak             allocates memory continuously (memory soak fail)
  --mode crash-on-event   exits(1) on an adverse platform event  (SIGUSR1)
  --mode hang-on-event    stays alive but stops answering after the event, and
                          does NOT recover when it clears (SIGUSR1/SIGUSR2)

SIGSTOP can't be caught (that's the OS freezing us). SIGCONT is the wake-from-
sleep signal. SIGUSR1/SIGUSR2 stand in for an injected adverse event and its
recovery (controller unplugged/replugged, network dropped/restored) — the
CoCert command hooks send exactly these in tests via `kill -USR1/-USR2 {pid}`.
Handlers are installed in every mode so a graceful title survives the events.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import threading
import time

STATE = {"hang": False}
_LEAK: list[bytearray] = []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ping-port", type=int, required=True)
    ap.add_argument(
        "--mode",
        choices=[
            "clean", "crash-on-resume", "hang-on-resume", "leak",
            "crash-on-event", "hang-on-event",
        ],
        default="clean",
    )
    ap.add_argument("--leak-rate-mb-s", type=float, default=8.0)
    args = ap.parse_args(argv)

    def on_cont(signum, frame):  # wake-from-sleep handler
        if args.mode == "crash-on-resume":
            os._exit(1)
        if args.mode == "hang-on-resume":
            STATE["hang"] = True

    def on_event(signum, frame):  # adverse platform event (controller/network)
        if args.mode == "crash-on-event":
            os._exit(1)
        if args.mode == "hang-on-event":
            STATE["hang"] = True
        # graceful modes: absorb the event, keep serving.

    def on_restore(signum, frame):  # event cleared
        # A well-behaved title recovers here. hang-on-event deliberately does
        # NOT clear the hang, modelling a game that never recovers.
        if args.mode != "hang-on-event":
            STATE["hang"] = False

    for sig, handler in (
        (signal.SIGCONT, on_cont),
        (signal.SIGUSR1, on_event),
        (signal.SIGUSR2, on_restore),
    ):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.ping_port))
    srv.listen(16)
    srv.settimeout(0.3)

    def serve() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                if STATE["hang"]:
                    # Alive but broken: refuse to answer.
                    continue
                try:
                    data = conn.recv(16)
                    if data.strip() == b"ping":
                        conn.sendall(b"pong")
                except OSError:
                    pass

    threading.Thread(target=serve, daemon=True).start()

    # Baseline footprint so RSS is measurable.
    _baseline = bytearray(20 * 1024 * 1024)  # noqa: F841

    tick = 0.2
    per_tick = int(args.leak_rate_mb_s * 1024 * 1024 * tick)
    while True:
        time.sleep(tick)
        if args.mode == "leak":
            _LEAK.append(bytearray(per_tick))


if __name__ == "__main__":
    main()
