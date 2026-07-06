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


# --- controller / network injectors (best-effort command hooks) ---

_SIGNAL_HOOKS = {
    "controller_disconnect_cmd": "kill -USR1 {pid}",
    "controller_reconnect_cmd": "kill -USR2 {pid}",
    "network_cut_cmd": "kill -USR1 {pid}",
    "network_restore_cmd": "kill -USR2 {pid}",
}


def _adapter_hooked(mode: str) -> DesktopAdapter:
    port = _free_port()
    cmd = [sys.executable, FIXTURE, "--ping-port", str(port), "--mode", mode]
    return DesktopAdapter(cmd, ping_port=port, hooks=dict(_SIGNAL_HOOKS))


class TestInjectorSkip(unittest.TestCase):
    """With no hook configured, controller/network must SKIP — never a false PASS."""

    def test_controller_skipped_without_hook(self):
        a = _adapter("clean")  # no hooks
        a.launch()
        try:
            r = run_scenario("controller_disconnect", a)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.SKIPPED)
        self.assertEqual(r.findings[0].type, FindingType.INJECTOR_UNAVAILABLE)

    def test_network_skipped_without_hook(self):
        a = _adapter("clean")
        a.launch()
        try:
            r = run_scenario("network_loss", a)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.SKIPPED)

    def test_cut_without_restore_hook_skips(self):
        # Refuse to cut network if we can't restore it.
        port = _free_port()
        cmd = [sys.executable, FIXTURE, "--ping-port", str(port), "--mode", "clean"]
        a = DesktopAdapter(cmd, ping_port=port, hooks={"network_cut_cmd": "true"})
        a.launch()
        try:
            r = run_scenario("network_loss", a)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.SKIPPED)


class TestControllerDisconnect(unittest.TestCase):
    def test_clean_game_recovers(self):
        a = _adapter_hooked("clean")
        a.launch()
        try:
            r = run_scenario("controller_disconnect", a, grace_s=4.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.PASS, r.findings)

    def test_crash_on_event_detected(self):
        a = _adapter_hooked("crash-on-event")
        a.launch()
        try:
            r = run_scenario("controller_disconnect", a, grace_s=4.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.FAIL)
        self.assertEqual(r.findings[0].type, FindingType.GAME_CRASH)

    def test_hang_on_event_detected(self):
        a = _adapter_hooked("hang-on-event")
        a.launch()
        try:
            r = run_scenario("controller_disconnect", a, grace_s=3.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.FAIL)
        self.assertEqual(r.findings[0].type, FindingType.RECOVERY_TIMEOUT)


class TestNetworkLoss(unittest.TestCase):
    def test_clean_game_recovers(self):
        a = _adapter_hooked("clean")
        a.launch()
        try:
            r = run_scenario("network_loss", a, grace_s=4.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.PASS, r.findings)

    def test_crash_on_event_detected(self):
        a = _adapter_hooked("crash-on-event")
        a.launch()
        try:
            r = run_scenario("network_loss", a, grace_s=4.0)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.FAIL)
        self.assertEqual(r.findings[0].type, FindingType.GAME_CRASH)


# --- v0.2: state-aware probe, multi-cycle torture, HTML report, web UI ---

class TestStateProbe(unittest.TestCase):
    def test_toy_target_reports_state(self):
        a = _adapter("clean")
        a.launch()
        try:
            # toy rotates menu -> loading -> gameplay
            state = a.probe_state()
        finally:
            a.terminate()
        self.assertIn(state, ("menu", "loading", "gameplay"))

    def test_v2_pong_with_state_still_counts_responsive(self):
        a = _adapter("clean")
        a.launch()
        try:
            self.assertTrue(a.is_responsive())
        finally:
            a.terminate()


class TestMultiCycle(unittest.TestCase):
    def test_clean_game_survives_three_cycles(self):
        a = _adapter("clean")
        a.launch()
        try:
            r = run_scenario("suspend_resume", a, hold_s=0.3, grace_s=4.0,
                             cycles=3, hold_jitter_s=0.2, gap_s=0.1)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.PASS, r.findings)
        self.assertEqual(r.details.get("cycles_completed"), 3)

    def test_crash_reports_failed_cycle(self):
        a = _adapter("crash-on-resume")
        a.launch()
        try:
            r = run_scenario("suspend_resume", a, hold_s=0.3, grace_s=3.0,
                             cycles=3, gap_s=0.1)
        finally:
            a.terminate()
        self.assertIs(r.outcome, Outcome.FAIL)
        self.assertEqual(r.details.get("failed_cycle"), 1)


class TestHtmlReport(unittest.TestCase):
    def test_html_contains_scenarios_and_verdict(self):
        from cocert.report import build_report, render_html
        a = _adapter("clean")
        results = run_suite(a, ["suspend_resume"])
        html = render_html(build_report(results, "toy"))
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Suspend / Resume", html)
        self.assertIn("CERTIFIABLE", html)

    def test_html_escapes_target(self):
        from cocert.report import build_report, render_html
        a = _adapter("clean")
        results = run_suite(a, ["suspend_resume"])
        html = render_html(build_report(results, "<script>alert(1)</script>"))
        self.assertNotIn("<script>alert(1)</script>", html)


class TestWebUi(unittest.TestCase):
    def test_index_status_and_runs_endpoints(self):
        import json as _json
        import tempfile
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from cocert.webui import RunState, make_handler

        with tempfile.TemporaryDirectory() as tmp:
            httpd = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(RunState(), tmp))
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                page = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/", timeout=3).read().decode()
                self.assertIn("CoCert", page)
                status = _json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/status", timeout=3).read())
                self.assertFalse(status["running"])
                runs = _json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/runs", timeout=3).read())
                self.assertEqual(runs, [])
                # path traversal must 404
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/runs/../../etc/report.html")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=3)
                self.assertEqual(ctx.exception.code, 404)
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
