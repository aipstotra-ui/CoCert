"""Integration + unit tests for the CoCert harness vertical slice (stdlib unittest).

The toy target (cocert/_fixtures/faultygame.py) is driven in each defect mode and
we assert the harness reports the exact finding. This is why the toy target is a
first-class deliverable: it makes detection deterministic without a real game.
"""

from __future__ import annotations

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cocert.desktop_adapter import DesktopAdapter, LaunchFailure  # noqa: E402
from cocert.models import FindingType, Outcome  # noqa: E402
from cocert.monitor import MemorySeries  # noqa: E402
from cocert.orchestrator import run_suite, suite_ok  # noqa: E402
from cocert.scenarios import run_scenario  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "cocert", "_fixtures", "faultygame.py")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _adapter(mode: str) -> DesktopAdapter:
    port = _free_port()
    cmd = [sys.executable, FIXTURE, "--ping-port", str(port), "--mode", mode]
    return DesktopAdapter(cmd, ping_port=port)


class TestSlopeMath(unittest.TestCase):
    def test_flat_series_zero_slope(self):
        s = MemorySeries([(0.0, 1000), (1.0, 1000), (2.0, 1000)])
        self.assertEqual(s.slope_bytes_per_s(), 0.0)

    def test_rising_series_positive_slope(self):
        s = MemorySeries([(0.0, 0), (1.0, 1000), (2.0, 2000)])
        self.assertAlmostEqual(s.slope_bytes_per_s(), 1000.0, places=3)

    def test_single_sample_no_slope(self):
        self.assertEqual(MemorySeries([(0.0, 500)]).slope_bytes_per_s(), 0.0)


class TestLaunch(unittest.TestCase):
    def test_bad_target_reports_launch_failure(self):
        adapter = DesktopAdapter([sys.executable, "/no/such/faulty.py", "--x"], ping_port=None)
        results = run_suite(adapter, ["suspend_resume"])
        self.assertEqual(len(results), 1)
        self.assertIs(results[0].outcome, Outcome.FAIL)
        self.assertEqual(results[0].findings[0].type, FindingType.LAUNCH_FAILURE)


class TestSuspendResume(unittest.TestCase):
    def test_clean_game_passes(self):
        a = _adapter("clean")
        a.launch()
        try:
            r = run_scenario("suspend_resume", a, hold_s=0.8, grace_s=5.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.PASS, r.findings)

    def test_crash_on_resume_detected(self):
        a = _adapter("crash-on-resume")
        a.launch()
        try:
            r = run_scenario("suspend_resume", a, hold_s=0.8, grace_s=4.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.FAIL)
        self.assertEqual(r.findings[0].type, FindingType.GAME_CRASH)

    def test_hang_on_resume_detected(self):
        a = _adapter("hang-on-resume")
        a.launch()
        try:
            r = run_scenario("suspend_resume", a, hold_s=0.8, grace_s=3.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.FAIL)
        self.assertEqual(r.findings[0].type, FindingType.RECOVERY_TIMEOUT)


class TestMemorySoak(unittest.TestCase):
    def test_clean_game_no_leak(self):
        a = _adapter("clean")
        a.launch()
        try:
            r = run_scenario("memory_soak", a, duration_s=2.5, interval_s=0.2)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.PASS, r.details)

    def test_leaky_game_flagged(self):
        a = _adapter("leak")
        a.launch()
        try:
            r = run_scenario("memory_soak", a, duration_s=2.5, interval_s=0.2)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.FAIL, r.details)
        self.assertEqual(r.findings[0].type, FindingType.MEMORY_LEAK)


class TestSuiteVerdict(unittest.TestCase):
    def test_suite_ok_true_when_no_failures(self):
        a = _adapter("clean")
        results = run_suite(a, ["suspend_resume", "memory_soak"])
        self.assertTrue(suite_ok(results), [r.to_dict() for r in results])


if __name__ == "__main__":
    unittest.main(verbosity=2)
