"""The relay on a real Modal GPU, as the page uses it, from Python: connect (timed, step by step), nvidia-smi
through the Jupyter kernel, then nn-fit's remote_train.py on cuda (steps/s), then end. A running relay first:

    cd box && uv run python -m box.gateway.relay --port 8790 &
    uv run --extra dev python -m box.gateway.prove_modal --gateway http://localhost:8790 \\
        --nn-fit ../../blogs-connect/blogs/web/embeds/nn-fit/remote_train.py [--attach s-...] [--keep]

The token is the [arb8020] profile of ~/.modal.toml (read here, never printed). --attach reuses a running
session (iterating without a new sandbox); --keep leaves it running. Writes a JSON summary to --out.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from box.gateway import kernel_client
from box.providers.modal import ModalToken

PROFILE = "arb8020"  # never herdora
NN_FIT_SECONDS = 10.0  # each nn-fit benchmark run
CONNECT_S = 15 * 60


def token(profile: str = PROFILE) -> ModalToken:
    assert profile != "herdora", "this proof never runs on the herdora workspace"
    return ModalToken.from_profile(profile)


def call(url: str, auth: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-Box-Token": auth, "Content-Type": "application/json"})  # fmt: skip
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def follow(gw: str, sid: str, auth: str, t0: float) -> list[dict]:
    """Print the SSE stream until running (or ended); returns the events with their elapsed time."""
    got = []
    with urllib.request.urlopen(f"{gw}/sessions/{sid}/events?token={auth}", timeout=CONNECT_S) as r:
        for raw in r:
            line = raw.decode().rstrip("\n")
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            event["elapsed"] = round(time.monotonic() - t0, 1)
            got.append(event)
            what = event.get("text") or event.get("status", {}).get("state")
            print(f"  {event['elapsed']:7.1f}s {event['kind']:6} {event.get('source', '')[:7]:7} {what}", flush=True)
            if event["kind"] == "status" and event["status"]["state"] in ("running", "ended"):
                return got
    raise RuntimeError("event stream closed before running")


def nn_fit_config(max_seconds: float) -> dict:
    """The widget's default: a 1-12-12-1 tanh net fitting a wave, float32, Adam lr 0.03 (sampled here)."""
    rng = random.Random(0)
    sizes = [1, 12, 12, 1]
    xs = [rng.uniform(-1, 1) for _ in range(200)]
    curve = [-1 + 2 * i / 320 for i in range(321)]

    def layer(n_in: int, n_out: int, scale: float) -> dict:
        return {"w": [rng.gauss(0, scale / math.sqrt(n_in)) for _ in range(n_in * n_out)], "b": [0.0] * n_out}

    def zeros(n_in: int, n_out: int) -> dict:
        return {"w": [0.0] * (n_in * n_out), "b": [0.0] * n_out}

    pairs = list(zip(sizes, sizes[1:], strict=False))
    return {
        "task": "regression", "activation": "tanh", "sizes": sizes, "lr": 0.03, "dtype": "float32",
        "state": {"layers": [layer(i, o, 1.0) for i, o in pairs], "adam": {"m": [zeros(i, o) for i, o in pairs], "v": [zeros(i, o) for i, o in pairs], "t": 0}},
        "train": {"x": xs, "y": [math.sin(3 * x) for x in xs]}, "test": {"x": curve, "y": [math.sin(3 * x) for x in curve]},
        "grid": curve, "step": 0, "seconds": 0, "max_steps": 10_000_000, "max_seconds": max_seconds, "tick_seconds": 0.1,
    }  # fmt: skip


def steps_per_s(lines: list[dict]) -> dict:
    start = next(line for line in lines if line["kind"] == "start")
    end = next(line for line in lines if line["kind"] == "end")
    return {"device": start["device"], "device_name": start["device_name"], "torch": start["torch"], "steps": end["step"],
            "seconds": round(end["seconds"], 2), "steps_per_s": round(end["step"] / end["seconds"]), "reason": end["reason"]}  # fmt: skip


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def nn_fit_remote(kernel: dict, program: Path) -> dict:
    config = nn_fit_config(NN_FIT_SECONDS)
    code = "\n".join([  # what the page sends (web/embeds/nn-fit/remote.ts: remoteCode)
        '_nn_fit = {"__name__": "nn_fit_remote"}',
        f"exec(compile({json.dumps(program.read_text())}, 'remote_train.py', 'exec'), _nn_fit)",
        "try:", f"    _nn_fit['run']({json.dumps(json.dumps(config))})", "finally:", "    del _nn_fit",
    ])  # fmt: skip
    out = kernel_client.run(kernel, code)
    assert out.status == "ok", (out.error, out.stderr[-2000:])
    return {**steps_per_s(json_lines(out.stdout)), "cell_s": round(out.seconds, 1)}


def nn_fit_local(program: Path) -> dict:
    config = json.dumps(nn_fit_config(NN_FIT_SECONDS))
    done = subprocess.run(["uv", "run", "--with", "torch", "python", str(program)], input=config, capture_output=True, text=True, check=True)
    return steps_per_s(json_lines(done.stdout))


def hold(kernel: dict, sid: str, tok: ModalToken, hold_s: float) -> dict:
    """An open (quiet) kernel websocket keeps the session past its idle timeout; once closed, the session
    ends idle. Asks the machine through the SDK (exec), never through the tunnel, which would count as use."""
    from box import sdk
    from box.providers.modal import Modal

    with Modal(token=tok, region="us") as modal:
        s = sdk.attach(modal, session_id=sid)
        url = kernel_client.api(kernel, f"/api/kernels/{kernel_client.kernel_id(kernel)}/channels").replace("http", "ws", 1)
        with kernel_client.connect(url, open_timeout=60):
            time.sleep(hold_s)
            held = s.status()
        closed = time.monotonic()
        ended = s.wait(timeout_s=hold_s + 600)
    return {"held_s": hold_s, "status_while_held": type(held).__name__, "ended": ended.reason, "close_to_end_s": round(time.monotonic() - closed, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", default="http://localhost:8790")
    ap.add_argument("--gpu", default="T4", type=lambda g: None if g == "none" else g, help="T4, or none (CPU)")
    ap.add_argument("--attach", help="a running session id: skip connect")
    ap.add_argument("--keep", action="store_true", help="leave the session running")
    ap.add_argument("--hold-s", type=float, help="keep-alive check: hold a kernel websocket open this long, then close it and time the idle end")
    ap.add_argument("--nn-fit", type=Path, help="remote_train.py (blogs/web/embeds/nn-fit)")
    ap.add_argument("--out", type=Path, default=Path(".evidence/prove_modal.json"))
    a = ap.parse_args()
    tok = token()
    auth = f"{tok.id}:{tok.secret}"
    summary: dict = {"gateway": a.gateway, "gpu": a.gpu}
    t0 = time.monotonic()
    if a.attach:
        sid = a.attach
    else:
        created = call(f"{a.gateway}/sessions", auth, "POST", {"provider": "modal", "token": {"id": tok.id, "secret": tok.secret}, "gpu": a.gpu, "labels": {"box.caller": "prove_modal"}})
        sid = created["session_id"]
        summary["post_ms"] = round(1000 * (time.monotonic() - t0))
        print(f"session {sid} (POST answered in {summary['post_ms']} ms)", flush=True)
        events = follow(a.gateway, sid, auth, t0)
        summary["connect_s"] = events[-1]["elapsed"]
        summary["steps"] = [(e["elapsed"], e.get("text") or e["status"]["state"]) for e in events if e["kind"] != "log"]
    summary["session_id"] = sid
    status = call(f"{a.gateway}/sessions/{sid}", auth)["status"]
    assert status["state"] == "running", status
    kernel = status["kernel"]
    try:
        if a.gpu is not None:
            smi = [kernel_client.run(kernel, "!nvidia-smi") for _ in range(3)]
            print(smi[0].stdout, flush=True)
            assert smi[0].status == "ok" and a.gpu in smi[0].stdout, smi[0]
            summary["nvidia_smi_cell_s"] = [round(o.seconds, 2) for o in smi]  # the first includes starting the kernel
        echo = [kernel_client.run(kernel, "print(1)") for _ in range(3)]
        summary["trivial_cell_s"] = [round(o.seconds, 3) for o in echo]
        if a.hold_s:
            summary["hold"] = hold(kernel, sid, tok, a.hold_s)
            print(f"hold: {summary['hold']}", flush=True)
        elif a.nn_fit:
            summary["nn_fit_remote"] = nn_fit_remote(kernel, a.nn_fit)
            print(f"nn-fit remote: {summary['nn_fit_remote']}", flush=True)
            summary["nn_fit_local"] = nn_fit_local(a.nn_fit)
            print(f"nn-fit local:  {summary['nn_fit_local']}", flush=True)
    finally:
        if not (a.keep or a.hold_s):  # a hold ends by itself (idle)
            summary["end"] = call(f"{a.gateway}/sessions/{sid}/end", auth, "POST")["status"]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
