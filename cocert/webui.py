"""CoCert local web dashboard — `cocert ui`.

A tester-friendly face on the harness: open a browser, pick a target, hit Run,
watch live status, browse past runs, open/share HTML reports. Stdlib-only
(http.server + threads); binds 127.0.0.1 ONLY — this is a local tool, never a
network service.

    browser --> GET  /              dashboard page (inline HTML/CSS/JS)
            --> POST /api/run       start a run (JSON config) in a worker thread
            --> GET  /api/status    live run state (poll ~1s)
            --> GET  /api/runs      history (from the runs dir)
            --> GET  /runs/<id>/report.html   stored shareable report

Runs are stored under ~/.cocert/runs/<timestamp>/ as report.json + report.html.
One run at a time: POST /api/run while busy returns 409.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .desktop_adapter import DesktopAdapter
from .orchestrator import run_suite
from .report import build_report, render_html, write_json
from .scenarios import DEFAULT_SCENARIOS, REGISTRY

DEFAULT_RUNS_DIR = os.path.expanduser("~/.cocert/runs")
_RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}$")


class RunState:
    """Shared state between the worker thread and /api/status. All writes go
    through methods that hold the lock; reads snapshot under the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.label = ""
        self.events: list[dict] = []
        self.last_run_id: str | None = None
        self.error: str | None = None

    def start(self, label: str) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.label = label
            self.events = []
            self.error = None
            return True

    def emit(self, event: str, payload: dict) -> None:
        with self._lock:
            self.events.append({"t": time.time(), "event": event, **payload})

    def finish(self, run_id: str | None, error: str | None = None) -> None:
        with self._lock:
            self.running = False
            self.last_run_id = run_id
            self.error = error

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "label": self.label,
                "events": list(self.events),
                "last_run_id": self.last_run_id,
                "error": self.error,
            }


def _fixture_cmd(mode: str, port: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "_faultygame", "--ping-port", str(port), "--mode", mode]
    return [sys.executable, "-m", "cocert.cli", "_faultygame",
            "--ping-port", str(port), "--mode", mode]


def _do_run(cfg: dict, state: RunState, runs_dir: str) -> None:
    """Worker thread body: build adapter from config, run, persist reports."""
    run_id = time.strftime("%Y%m%d-%H%M%S")
    try:
        ping_port = int(cfg.get("ping_port") or 8790)
        if cfg.get("demo_mode"):
            cmd = _fixture_cmd(str(cfg["demo_mode"]), ping_port)
            hooks = {
                "controller_disconnect_cmd": "kill -USR1 {pid}",
                "controller_reconnect_cmd": "kill -USR2 {pid}",
                "network_cut_cmd": "kill -USR1 {pid}",
                "network_restore_cmd": "kill -USR2 {pid}",
            }
            label = f"demo ({cfg['demo_mode']})"
        else:
            cmd = shlex.split(str(cfg.get("cmd", "")))
            if not cmd:
                state.finish(None, "no game command given")
                return
            hooks = {k: str(v) for k, v in (cfg.get("hooks") or {}).items() if v}
            label = cfg.get("cmd", "")

        scenarios = [s for s in (cfg.get("scenarios") or DEFAULT_SCENARIOS)
                     if s in REGISTRY]
        params: dict[str, dict] = {}
        cycles = int(cfg.get("cycles") or 1)
        if cycles > 1:
            params["suspend_resume"] = {"cycles": cycles, "hold_jitter_s": 1.0}
        soak_s = float(cfg.get("soak_s") or 0)
        if soak_s > 0:
            params["memory_soak"] = {"duration_s": soak_s}

        adapter = DesktopAdapter(cmd, ping_port=ping_port, hooks=hooks)
        results = run_suite(adapter, scenarios, params, progress=state.emit)
        report = build_report(results, label)

        out_dir = os.path.join(runs_dir, run_id)
        os.makedirs(out_dir, exist_ok=True)
        write_json(report, os.path.join(out_dir, "report.json"))
        with open(os.path.join(out_dir, "report.html"), "w") as fh:
            fh.write(render_html(report))
        state.finish(run_id)
    except Exception as exc:  # noqa: BLE001 — surface, never crash the server
        state.finish(None, f"{type(exc).__name__}: {exc}")


def _list_runs(runs_dir: str) -> list[dict]:
    out = []
    if not os.path.isdir(runs_dir):
        return out
    for rid in sorted(os.listdir(runs_dir), reverse=True)[:50]:
        path = os.path.join(runs_dir, rid, "report.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as fh:
                rep = json.load(fh)
            out.append({"id": rid, "target": rep.get("target", "?"),
                        "summary": rep.get("summary", {}),
                        "generated_at": rep.get("generated_at", "")})
        except (OSError, json.JSONDecodeError):
            continue
    return out


def make_handler(state: RunState, runs_dir: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802 — http.server API
            if self.path == "/" or self.path == "/index.html":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(200, state.snapshot())
            elif self.path == "/api/runs":
                self._json(200, _list_runs(runs_dir))
            elif self.path.startswith("/runs/"):
                # /runs/<id>/report.html — id strictly validated, no traversal.
                parts = self.path.strip("/").split("/")
                if (len(parts) == 3 and _RUN_ID_RE.match(parts[1])
                        and parts[2] in ("report.html", "report.json")):
                    fpath = os.path.join(runs_dir, parts[1], parts[2])
                    if os.path.isfile(fpath):
                        ctype = ("text/html; charset=utf-8"
                                 if fpath.endswith(".html") else "application/json")
                        with open(fpath, "rb") as fh:
                            self._send(200, fh.read(), ctype)
                        return
                self._json(404, {"error": "not found"})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/run":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                cfg = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid JSON"})
                return
            label = cfg.get("demo_mode") or cfg.get("cmd") or "run"
            if not state.start(str(label)):
                self._json(409, {"error": "a run is already in progress"})
                return
            threading.Thread(target=_do_run, args=(cfg, state, runs_dir),
                             daemon=True).start()
            self._json(202, {"started": True})

    return Handler


def serve(port: int = 8737, runs_dir: str = DEFAULT_RUNS_DIR,
          open_browser: bool = True) -> None:
    os.makedirs(runs_dir, exist_ok=True)
    state = RunState()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, runs_dir))
    url = f"http://127.0.0.1:{port}"
    print(f"CoCert dashboard: {url}   (Ctrl-C to stop)")
    print(f"Run history: {runs_dir}")
    if open_browser:
        import webbrowser
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


# --- the dashboard page (inline, self-contained) ---

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CoCert — pre-cert torture testing</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body { font: 15px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
         background: #010409; color: #e6edf3; }
  .wrap { max-width: 860px; margin: 0 auto; padding: 36px 20px 60px; }
  h1 { font-size: 24px; letter-spacing: -0.4px; }
  h1 small { color: #4c9aff; }
  .tagline { color: #8b949e; margin: 4px 0 28px; }
  h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 1px;
       color: #8b949e; margin: 28px 0 12px; }
  .panel { background: #0d1117; border: 1px solid #21262d; border-radius: 12px;
           padding: 20px; }
  label { display: block; font-size: 13px; color: #8b949e; margin: 12px 0 4px; }
  input, select { width: 100%; background: #010409; color: #e6edf3;
    border: 1px solid #30363d; border-radius: 8px; padding: 9px 12px;
    font: inherit; }
  input:focus, select:focus { outline: none; border-color: #4c9aff; }
  .row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  .btn { background: #238636; color: #fff; border: 0; border-radius: 8px;
         padding: 11px 22px; font: 600 15px/1 inherit; cursor: pointer;
         margin-top: 16px; }
  .btn:hover { background: #2ea043; }
  .btn[disabled] { background: #21262d; color: #8b949e; cursor: not-allowed; }
  .btn.demo { background: #1f6feb; }
  .btn.demo:hover { background: #388bfd; }
  .tabs { display: flex; gap: 8px; margin-bottom: 14px; }
  .tab { background: #161b22; border: 1px solid #30363d; color: #8b949e;
         border-radius: 999px; padding: 6px 16px; cursor: pointer; font-size: 13px; }
  .tab.active { color: #e6edf3; border-color: #4c9aff; }
  #live { display: none; margin-top: 16px; }
  .evt { font: 13px/1.7 ui-monospace, monospace; color: #8b949e; }
  .evt b.ok { color: #12b76a; } .evt b.bad { color: #f04438; }
  .evt b.skip { color: #f79009; }
  .spinner { display: inline-block; width: 12px; height: 12px; border-radius: 50%;
    border: 2px solid #30363d; border-top-color: #4c9aff;
    animation: spin 0.8s linear infinite; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; color: #8b949e; font-weight: 500; font-size: 12px;
       text-transform: uppercase; letter-spacing: 0.5px; padding: 8px 10px; }
  td { padding: 10px; border-top: 1px solid #21262d; }
  tr:hover td { background: #161b22; }
  .pill { font-size: 12px; font-weight: 700; padding: 2px 10px; border-radius: 999px; }
  .pill.ok { background: #12b76a22; color: #12b76a; }
  .pill.bad { background: #f0443822; color: #f04438; }
  .pill.warn { background: #f7900922; color: #f79009; }
  a { color: #4c9aff; text-decoration: none; }
  .muted { color: #484f58; font-size: 13px; }
</style></head><body><div class="wrap">
<h1>CoCert <small>// pre-cert torture testing</small></h1>
<p class="tagline">Break your game the way certification will — before Sony, Microsoft or Nintendo do.</p>

<div class="panel">
  <div class="tabs">
    <div class="tab active" id="tab-demo" onclick="setTab('demo')">Demo game</div>
    <div class="tab" id="tab-real" onclick="setTab('real')">My game build</div>
  </div>

  <div id="pane-demo">
    <label>Demo defect mode — pick how the fake game misbehaves</label>
    <select id="demo-mode">
      <option value="clean">clean — well-behaved game (everything passes)</option>
      <option value="crash-on-resume">crash-on-resume — dies waking from sleep</option>
      <option value="hang-on-resume">hang-on-resume — freezes after waking</option>
      <option value="leak">leak — slowly eats memory</option>
      <option value="crash-on-event">crash-on-event — dies on controller/network loss</option>
      <option value="hang-on-event">hang-on-event — freezes on controller/network loss</option>
    </select>
    <button class="btn demo" id="btn-demo" onclick="runDemo()">Run demo test</button>
  </div>

  <div id="pane-real" style="display:none">
    <label>Game launch command</label>
    <input id="cmd" placeholder="./MyGame --windowed">
    <div class="row">
      <div><label>Ping port (SDK hook)</label><input id="ping" value="8790"></div>
      <div><label>Suspend cycles</label><input id="cycles" value="5"></div>
      <div><label>Soak seconds</label><input id="soak" value="60"></div>
    </div>
    <p class="muted" style="margin-top:10px">The ping hook is ~10 lines in your build
      — see docs/sdk-hook.md. Without it, hang detection is limited.</p>
    <button class="btn" id="btn-real" onclick="runReal()">Run torture test</button>
  </div>

  <div id="live"><h2 style="margin-top:4px">Live run</h2><div id="events" class="evt"></div></div>
</div>

<h2>Past runs</h2>
<div class="panel" id="history"><p class="muted">No runs yet — try the demo above.</p></div>

<script>
let polling = null;
function setTab(t) {
  document.getElementById('pane-demo').style.display = t==='demo'?'':'none';
  document.getElementById('pane-real').style.display = t==='real'?'':'none';
  document.getElementById('tab-demo').classList.toggle('active', t==='demo');
  document.getElementById('tab-real').classList.toggle('active', t==='real');
}
async function post(cfg) {
  const r = await fetch('/api/run', {method:'POST', body: JSON.stringify(cfg)});
  if (r.status === 409) { alert('A run is already in progress.'); return; }
  document.getElementById('live').style.display = 'block';
  document.getElementById('events').innerHTML =
    '<span class="spinner"></span>starting…';
  setBusy(true);
  if (!polling) polling = setInterval(poll, 1000);
}
function setBusy(b) {
  document.getElementById('btn-demo').disabled = b;
  document.getElementById('btn-real').disabled = b;
}
function runDemo() { post({demo_mode: document.getElementById('demo-mode').value}); }
function runReal() {
  const cmd = document.getElementById('cmd').value.trim();
  if (!cmd) { alert('Enter the command that launches your game build.'); return; }
  post({cmd, ping_port: document.getElementById('ping').value,
        cycles: document.getElementById('cycles').value,
        soak_s: document.getElementById('soak').value});
}
function evtLine(e) {
  if (e.event === 'launch') return 'launching target… scenarios: ' + e.scenarios.join(', ');
  if (e.event === 'scenario_start') return '&#9654; ' + e.name + ' running…';
  if (e.event === 'scenario_end') {
    const cls = e.outcome === 'PASS' ? 'ok' : (e.outcome === 'SKIPPED' ? 'skip' : 'bad');
    return '&#8226; ' + e.name + ' → <b class="' + cls + '">' + e.outcome + '</b>';
  }
  if (e.event === 'done') return e.ok ? '<b class="ok">run complete</b>'
                                      : '<b class="bad">run complete (failures)</b>';
  return e.event;
}
async function poll() {
  const s = await (await fetch('/api/status')).json();
  const el = document.getElementById('events');
  el.innerHTML = s.events.map(evtLine).join('<br>') +
    (s.running ? '<br><span class="spinner"></span>working…' : '');
  if (s.error) el.innerHTML += '<br><b class="bad">error: ' + s.error + '</b>';
  if (!s.running) {
    clearInterval(polling); polling = null; setBusy(false); loadHistory();
    if (s.last_run_id) window.open('/runs/' + s.last_run_id + '/report.html', '_blank');
  }
}
function pill(sum) {
  if (sum.failed > 0) return '<span class="pill bad">FAILED</span>';
  if (sum.skipped > 0) return '<span class="pill warn">PARTIAL</span>';
  return '<span class="pill ok">CERTIFIABLE</span>';
}
async function loadHistory() {
  const runs = await (await fetch('/api/runs')).json();
  const h = document.getElementById('history');
  if (!runs.length) { h.innerHTML = '<p class="muted">No runs yet — try the demo above.</p>'; return; }
  h.innerHTML = '<table><tr><th>When</th><th>Target</th><th>Result</th><th>P/F/S</th><th></th></tr>' +
    runs.map(r => '<tr><td>' + r.id + '</td><td>' + r.target + '</td><td>' +
      pill(r.summary) + '</td><td>' + r.summary.passed + '/' + r.summary.failed +
      '/' + r.summary.skipped + '</td><td><a href="/runs/' + r.id +
      '/report.html" target="_blank">report</a></td></tr>').join('') + '</table>';
}
loadHistory();
</script></div></body></html>
"""
