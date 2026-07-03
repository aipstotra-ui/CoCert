"""PlatformAdapter — the seam that keeps the console vision alive.

The scenario logic never talks to the OS directly. It talks to a
PlatformAdapter. Today the only implementation is DesktopAdapter (a game's
PC build). Tomorrow a ConsoleAdapter for a Sony/MS/Nintendo devkit slots in
behind the exact same interface, and the scenarios do not change.

    +-------------------+        +---------------------------+
    | ScenarioRunner    | -----> | PlatformAdapter (ABC)     |
    +-------------------+        +------------+--------------+
                                              |
                          +-------------------+-------------------+
                          |                                       |
                 +--------v---------+                    +--------v---------+
                 | DesktopAdapter   |  (implemented)     | ConsoleAdapter   | (future,
                 | psutil/stdlib    |                    | devkit SDK       |  behind NDA)
                 +------------------+                    +------------------+
"""

from __future__ import annotations

import abc


class InjectorUnavailable(Exception):
    """Raised by an adapter method when the action cannot run on this host
    (missing privileges, no controller, unsupported OS). The scenario turns
    this into a SKIPPED result, never a PASS."""


class PlatformAdapter(abc.ABC):
    @abc.abstractmethod
    def launch(self) -> None:
        """Start the target. Raises LaunchFailure via RuntimeError on failure."""

    @abc.abstractmethod
    def is_alive(self) -> bool:
        """True if the target process (tree) is still running."""

    @abc.abstractmethod
    def is_responsive(self, timeout: float = 1.0) -> bool:
        """True if the target answers a liveness probe within `timeout`."""

    @abc.abstractmethod
    def suspend(self) -> None:
        """Freeze the target (console 'sleep')."""

    @abc.abstractmethod
    def resume(self) -> None:
        """Wake the target (console 'resume')."""

    @abc.abstractmethod
    def sample_memory_bytes(self) -> int:
        """Current resident memory of the target tree, in bytes."""

    @abc.abstractmethod
    def terminate(self) -> None:
        """Stop the target and clean up."""

    # Best-effort injectors — default to unavailable so a console adapter or a
    # richer desktop build can override them without every adapter reimplementing.
    def disconnect_controller(self) -> None:
        raise InjectorUnavailable("controller disconnect not supported by this adapter")

    def reconnect_controller(self) -> None:
        raise InjectorUnavailable("controller reconnect not supported by this adapter")

    def cut_network(self) -> None:
        raise InjectorUnavailable("network cut not supported by this adapter")

    def restore_network(self) -> None:
        raise InjectorUnavailable("network restore not supported by this adapter")
