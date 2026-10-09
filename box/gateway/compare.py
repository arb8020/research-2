"""The A/B/C comparison table: scenarios.py's measured runs (results/{live,deadline,latency}.json)
plus the static facts (5) token location and (6) code weight, read from the code here.

    cd box && uv run python -m box.gateway.compare     # -> gateway-do/results/comparison.json + a markdown table on stdout
"""

from __future__ import annotations

import json
from pathlib import Path

BOX = Path(__file__).resolve().parents[1]
RESULTS = BOX / "gateway-do" / "results"
DO = "gateway-do/src/"
WORKER = [f"{DO}{f}" for f in ("index.ts", "hub.ts", "types.ts", "relay.ts", "event-log.ts", "sse.ts")]
PUSH = ["gateway/push.py", "gateway/forwarder.py"]
FILES = {  # what each variant adds on top of the box SDK (sdk.py, supervisor.py, modal_provider.py: all three)
    "A": ["gateway/relay.py", "gateway/kernel.Dockerfile"],
    "B": ["gateway/relay.py", "gateway/kernel.Dockerfile", *PUSH, *WORKER, f"{DO}owner-do.ts", f"{DO}proxy.ts"],
    "C": ["gateway/relay.py", "gateway/kernel.Dockerfile", *PUSH, *WORKER, f"{DO}fanout-do.ts"],
}

STATIC = {
    "token": {
        "A": "browser localStorage; sent on every call; the relay holds it for one request (or the boot thread), keeps a sha256 digest "
             "(relay.py digest/Boot.token_digest). Jupyter token = HMAC(secret, session) (relay.py kernel_token): derived, never stored.",
        "B": "as A on the relay, plus: OwnerDO stores the reader's Modal token {id, secret} in DO SQLite from create until the session "
             "ends (owner-do.ts created -> setEnded drops it), and Jupyter's token (upstream); the browser gets a DO-minted kernel token.",
        "C": "as A on the relay; the Worker passes it through (never stored); FanoutDO keeps only a sha256 digest. The ring holds the "
             "running status, so the derived Jupyter token sits in DO SQLite while the ring keeps that event.",
    },
    "authority": {
        "A": "the machine (supervisor: lease, deadline, idle). The relay keeps boot records in memory <=10 min (rebuildable).",
        "B": "two: the DO (status, deadline alarm, token, kernel proxy) and the machine (idle, backstop deadline = DO's + 120 s).",
        "C": "the machine, as A. The DO is a cache (event ring + digest): lose it and only replay is lost.",
    },
    "deploy": {
        "A": "one Python process the browser can reach (dev: localhost) + the reader's Modal.",
        "B": "A's relay reachable by the Worker (dev: cloudflared quick tunnel) + Worker + 1 SQLite DO class + PUSH_SECRET; machine egress to workers.dev.",
        "C": "same as B (different DO class).",
    },
}


def loc(rel: str) -> dict[str, int]:
    lines = (BOX / rel).read_text().splitlines()
    code = [line for line in lines if line.strip() and not line.strip().startswith(("#", "//"))]
    return {"lines": len(lines), "code": len(code)}


def code_weight() -> dict[str, dict]:
    out = {}
    for variant, files in FILES.items():
        per = {f: loc(f) for f in files}
        out[variant] = {"files": per, "code": sum(v["code"] for v in per.values()), "lines": sum(v["lines"] for v in per.values())}
    return out


def load(run: str) -> dict:
    path = RESULTS / f"{run}.json"
    return json.loads(path.read_text())["variants"] if path.exists() else {}


def row(name: str, cells: dict[str, object]) -> str:
    return f"| {name} | " + " | ".join(str(cells.get(v, "-")) for v in "ABC") + " |"


def table(weight: dict, live: dict, deadline: dict, latency: dict) -> list[str]:
    def get(d: dict, v: str, *path: str) -> object:
        cur: object = d.get(v, {})
        for p in path:
            cur = cur.get(p, "-") if isinstance(cur, dict) else "-"
        return cur

    def dies(v: str) -> str:
        saw = get(live, v, "machine_dies", "reader_saw")
        seen = saw if isinstance(saw, list) else []
        status = next((e for e in seen if e["kind"] == "status"), None)
        if status is not None:
            return f"ended({status['what']['reason']}) after {status['after_s']} s"
        return f"only a step ('machine silent') after {seen[0]['after_s']} s" if seen else "nothing"

    def ended(v: str, which: str) -> str:
        e = get(deadline, v, which)
        return f"{e.get('reason')} at +{e.get('ended_after_running_s')} s (late {e.get('late_vs_deadline_s')} s)" if isinstance(e, dict) and "reason" in e else "-"

    rows = [
        ("(1) machine killed: reader's stream shows", {v: dies(v) for v in "ABC"}),
        ("(1) GET after the kill", {v: f"{get(live, v, 'machine_dies', 'get_after', 'code')} {get(live, v, 'machine_dies', 'get_after', 'status', 'reason')}" for v in "ABC"}),
        ("(1) logs survive (fresh tab replays the mid-run lines)", {v: f"{get(live, v, 'machine_dies', 'fresh_tab', 'run_lines_replayed')}/{get(live, v, 'machine_dies', 'run_lines_before_kill')}" for v in "ABC"}),
        ("(1) recovery: new session connect (CPU)", {v: f"{get(live, v, 'recovery', 'connect_s')} s" for v in "ABC"}),
        ("(2) reattach (Last-Event-ID): first event", {v: f"{get(live, v, 'reattach', 'resume_first_event_ms')} ms, repeats {get(live, v, 'reattach', 'resume_repeats')}" for v in "ABC"}),
        ("(2) reload (no id): full replay", {v: f"{get(live, v, 'reattach', 'reload_full_replay_ms')} ms" for v in "ABC"}),
        ("(2) GET /sessions/{id} p50", {v: f"{get(live, v, 'reattach', 'get_ms_p50')} ms" for v in "ABC"}),
        ("(3) two tabs: same lines, same order", {v: f"{get(live, v, 'two_tabs', 'both_saw_all')}/{get(live, v, 'two_tabs', 'same_order')}" for v in "ABC"}),
        ("(3) machine log line -> tab, p50 / max", {v: f"{(get(live, v, 'two_tabs', 'lat_ms_p50') or ['-'])[0]} / {(get(live, v, 'two_tabs', 'lat_ms_max') or ['-'])[0]} ms" for v in "ABC"}),
        ("(4) left alone (idle 60 s)", {v: ended(v, "idle") for v in "ABC"}),
        ("(4) kernel held open (deadline 180 s)", {v: ended(v, "deadline") for v in "ABC"}),
        ("(6) code over the box SDK (non-blank, non-comment lines)", {v: weight[v]["code"] for v in "ABC"}),
        ("(7) connect T4 (POST -> running)", {v: f"{get(latency, v, 'connect_s')} s" for v in "ABC"}),
        ("(7) first cell (kernel start + nvidia-smi)", {v: f"{get(latency, v, 'first_cell_s')} s" for v in "ABC"}),
        ("(7) cell RTT p50 / p90", {v: f"{get(latency, v, 'cell_rtt_ms_p50')} / {get(latency, v, 'cell_rtt_ms_p90')} ms" for v in "ABC"}),
        ("(7) end (POST /end -> ended)", {v: f"{get(latency, v, 'end_s')} s" for v in "ABC"}),
    ]
    return ["| scenario | A relay | B do-owns | C fanout |", "|---|---|---|---|", *(row(n, c) for n, c in rows)]


def main() -> None:
    weight = code_weight()
    live, deadline, latency = load("live"), load("deadline"), load("latency")
    out = {"static": STATIC, "code_weight": weight, "live": live, "deadline": deadline, "latency": latency}
    (RESULTS / "comparison.json").write_text(json.dumps(out, indent=2))
    print("\n".join(table(weight, live, deadline, latency)))


if __name__ == "__main__":
    main()
