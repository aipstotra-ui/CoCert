"""CertHarness — platform-state torture harness for game builds.

MVP scope: drive a desktop game build through the console-cert failure
scenarios that do not require playing the game (suspend/resume, controller
disconnect, network loss, long-session memory) and detect crash / hang /
memory-leak / failed-recovery with named findings.

Console (Sony/MS/Nintendo) devkit support is deferred behind PlatformAdapter.
"""

__version__ = "0.1.0"
