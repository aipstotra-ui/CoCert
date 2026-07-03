# The CoCert liveness hook (optional, ~10 lines)

CoCert measures whether your game is *responsive* — not just alive — after it
suspends/resumes it, disconnects a controller, or drops the network. Without
help, it can only tell if the process is still running (a heuristic: a hung game
is still "alive"). With a tiny hook, the check becomes exact.

## What to add

Have your build open a TCP socket on `127.0.0.1:<port>` and answer `ping` with
`pong` from your main loop (or a thread that's healthy only when the main loop
is). If your loop is wedged, stop answering — that's how CoCert sees a hang.

### Example (C#/Unity-ish pseudocode)

```csharp
// Start once, on a background thread.
var listener = new TcpListener(IPAddress.Loopback, 8790);
listener.Start();
while (running) {
    using var client = listener.AcceptTcpClient();
    using var stream = client.GetStream();
    var buf = new byte[16];
    int n = stream.Read(buf, 0, buf.Length);
    if (Encoding.ASCII.GetString(buf, 0, n).Trim() == "ping"
        && MainLoopHealthy())            // <-- only answer when truly healthy
        stream.Write(Encoding.ASCII.GetBytes("pong"));
}
```

`MainLoopHealthy()` should reflect real progress (e.g. a frame counter advanced
in the last N ms), so a frozen render/update loop stops ponging.

Then run:

```bash
cocert run --cmd "./MyGame" --ping-port 8790
```

Reference implementation: `cocert/_fixtures/faultygame.py` (the toy target) does
exactly this in ~10 lines.

## Controller / network injection hooks

The actual "unplug the controller" or "cut the network" action depends on your
test rig, so CoCert delegates it to a command you supply. It runs your
disconnect command, checks the game survives, then runs your reconnect command
and checks recovery. `{pid}` expands to the game's process id.

```bash
cocert run --cmd "./MyGame" --ping-port 8790 \
  --controller-disconnect-cmd "python rig/pad.py off" \
  --controller-reconnect-cmd  "python rig/pad.py on" \
  --network-cut-cmd     "sudo pfctl -e -f rig/block.conf" \
  --network-restore-cmd "sudo pfctl -d"
```

If you don't supply both the cut and the restore command for a category, that
scenario reports **SKIPPED** — CoCert never claims a category passed when it
couldn't actually run it. Both commands are required so it never disconnects
something it can't reconnect.
