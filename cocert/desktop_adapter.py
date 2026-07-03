"""DesktopAdapter — runs a game's PC build, stdlib only (no third-party deps).

Design choices for the MVP:
- suspend/resume via SIGSTOP / SIGCONT (Unix). This is exactly what a console
  'sleep' does to a title: freeze every thread, then thaw it. psutil is the
  documented upgrade for Windows (SuspendThread) but is NOT required here.
- responsiveness via a TCP liveness probe. Real games expose this with a tiny
  optional SDK hook (a local socket that answers "ping" with "pong"); our toy
  target does the same, so detection is exact in tests. Without the hook a
  future version falls back to window/CPU heuristics.
- memory via `ps -o rss=` summed across the process tree (KB -> bytes).
- process TREE tracking: games are often launched by a wrapper/launcher, so we
  resolve children with `pgrep -P` and monitor the whole tree.
"""

from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import time

from .adapter import InjectorUnavailable, PlatformAdapter


class LaunchFailure(RuntimeError):
    pass


def _child_pids(pid: int) -> list[int]:
    try:
        out = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    pids: list[int] = []
    for line in out.stdout.split():
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def _tree_pids(root: int) -> list[int]:
    seen: list[int] = []
    frontier = [root]
    while frontier:
        pid = frontier.pop()
        if pid in seen:
            continue
        seen.append(pid)
        frontier.extend(_child_pids(pid))
    return seen


def _rss_bytes(pids: list[int]) -> int:
    if not pids:
        return 0
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return 0
    total_kb = 0
    for line in out.stdout.split():
        try:
            total_kb += int(line)
        except ValueError:
            continue
    return total_kb * 1024  # ps reports RSS in KiB on macOS/Linux


class DesktopAdapter(PlatformAdapter):
    def __init__(
        self,
        cmd: list[str],
        ping_port: int | None = None,
        hooks: dict[str, str] | None = None,
    ):
        """cmd: argv to launch the game build. ping_port: liveness-probe port
        if the build exposes the (optional) SDK hook. hooks: tester-supplied
        shell commands for injectors this host can't do natively — keys
        'controller_disconnect_cmd', 'controller_reconnect_cmd',
        'network_cut_cmd', 'network_restore_cmd'. A '{pid}' placeholder in the
        command is filled with the target pid."""
        self._cmd = cmd
        self._ping_port = ping_port
        self._hooks = hooks or {}
        self._proc: subprocess.Popen | None = None

    # --- lifecycle ---
    def launch(self) -> None:
        try:
            self._proc = subprocess.Popen(self._cmd)
        except (OSError, ValueError) as exc:
            raise LaunchFailure(f"could not launch target {self._cmd!r}: {exc}") from exc
        # Give it a moment to fail fast (bad binary, missing lib).
        time.sleep(0.3)
        if self._proc.poll() is not None:
            raise LaunchFailure(
                f"target exited immediately with code {self._proc.returncode}"
            )

    @property
    def pid(self) -> int:
        if self._proc is None:
            raise RuntimeError("launch() not called")
        return self._proc.pid

    def is_alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def exit_code(self) -> int | None:
        if self._proc is None:
            return None
        return self._proc.poll()

    # --- probes ---
    def is_responsive(self, timeout: float = 1.0) -> bool:
        if not self.is_alive():
            return False
        if self._ping_port is None:
            # No SDK hook: fall back to "process is alive". Documented as a
            # heuristic; the toy target and integrated builds use the hook.
            return True
        try:
            with socket.create_connection(("127.0.0.1", self._ping_port), timeout) as s:
                s.settimeout(timeout)
                s.sendall(b"ping")
                data = s.recv(16)
                return data.strip() == b"pong"
        except OSError:
            return False

    def sample_memory_bytes(self) -> int:
        if self._proc is None:
            return 0
        return _rss_bytes(_tree_pids(self._proc.pid))

    # --- state injection ---
    def suspend(self) -> None:
        # SIGSTOP the whole tree so a launcher-spawned game is frozen too.
        for pid in _tree_pids(self.pid):
            try:
                os.kill(pid, signal.SIGSTOP)
            except ProcessLookupError:
                continue

    def resume(self) -> None:
        for pid in _tree_pids(self.pid):
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                continue

    # --- best-effort injectors via tester-supplied command hooks ---
    # The actual disconnect/network mechanism is studio- and rig-specific, so we
    # delegate to a command the tester provides. We require BOTH the inject and
    # the restore command up front: never disconnect a thing we can't reconnect.
    def _run_hook(self, key: str, label: str) -> None:
        cmd = self._hooks.get(key)
        if not cmd:
            raise InjectorUnavailable(
                f"{label}: no '{key}' configured — pass --{key.replace('_', '-')}"
            )
        filled = cmd.format(pid=self.pid)
        try:
            subprocess.run(
                shlex.split(filled), timeout=10, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InjectorUnavailable(f"{label}: hook command failed: {exc}") from exc

    def disconnect_controller(self) -> None:
        if not self._hooks.get("controller_reconnect_cmd"):
            raise InjectorUnavailable(
                "controller disconnect: no reconnect hook configured — refusing "
                "to disconnect without a way to reconnect"
            )
        self._run_hook("controller_disconnect_cmd", "controller disconnect")

    def reconnect_controller(self) -> None:
        self._run_hook("controller_reconnect_cmd", "controller reconnect")

    def cut_network(self) -> None:
        if not self._hooks.get("network_restore_cmd"):
            raise InjectorUnavailable(
                "network cut: no restore hook configured — refusing to cut "
                "network without a way to restore it"
            )
        self._run_hook("network_cut_cmd", "network cut")

    def restore_network(self) -> None:
        self._run_hook("network_restore_cmd", "network restore")

    def terminate(self) -> None:
        if self._proc is None:
            return
        try:
            # Resume first: a suspended process can't be reaped cleanly.
            self.resume()
        except Exception:
            pass
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=3)
