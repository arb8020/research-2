# Reader-path gateway: A vs B vs C (2026-10-09, overnight)

Decision 3 in `box/DECISIONS-reader-path.md`: who owns a reader's session. All three speak
`box/CONTRACT-gateway.md`, so the page doesn't change between them (`?gateway=URL`).

- **A relay**: the machine owns the session (its supervisor). A stateless Python relay over the box SDK.
- **C fanout**: as A, plus a Cloudflare Durable Object in front that only fans events out.
- **B do-owns**: the Durable Object owns the session (status, deadline, the reader's token, a kernel proxy) and calls the relay to make and end machines.

Raw results are in `results/{live,deadline,latency,comparison}.json`. Page proofs (Playwright videos + screenshots) are in `.evidence/verify_connect-{B,C}/`, gitignored.

## What was built

```
box/gateway/
~   relay.py          # (A) + one seam: Config.push. None = A unchanged. Set: boot events go to a fan-out, and a forwarder service starts on the machine
+   push.py           # the relay's half of B/C: one sender thread, NDJSON batches, push key = HMAC(secret, "push:"+id)
+   forwarder.py      # on the machine (stdlib), a box service beside Jupyter: tails Jupyter's log, heartbeats every 5 s,
                      #   pushes the session's end (the supervisor's reason) on SIGTERM. A killed machine goes silent.
+   scenarios.py      # the harness: live | deadline | latency runs, against any variant by base URL
+   compare.py        # static facts (token location, LOC) + results -> results/comparison.json + the table below
+   local_stack.py    # A/B/C relays on the local provider, for `wrangler dev` (no cloud)
box/gateway-do/       # was the spike's gateway-cf
+   src/index.ts      # Worker: /b and /c prefixes; CORS, routing, push-key check; (C) forwards GET/end to the relay
+   src/hub.ts        # base DO for both: SQLite ring + SSE + Last-Event-ID, push ingest, the "silent machine" alarm
+   src/fanout-do.ts  # (C) 15 lines: passes events through, keeps a token digest, says "silent" and nothing more
+   src/owner-do.ts   # (B) canonical status, token until the end, deadline alarm -> relay end, silent -> ask the relay, kernel proxy
+   src/relay.ts      # calls to the Python relay
~   src/types.ts      # contract types + boundary parsers (unix seconds, like the relay)
    src/{event-log,sse,proxy}.ts   # from the spike, unchanged
+   scripts/up.sh, down.sh         # 3 relays (:8780 A, :8781 C, :8782 B) + 2 quick tunnels + wrangler deploy
box/tests/test_push.py  # relay --push on the local provider: boot -> machine log -> end, heartbeat, idle reason, kill = silence
```

**Two DO classes over one base, not one class with a mode.** B and C differ in what a pushed status means, what a silent machine means, whether a deadline exists, and whether the kernel is proxied. A mode would put an `if` in each of those. Subclasses keep each variant's behaviour in one file: (C) is 15 lines, (B) 117. That also makes code weight (6) countable.

**One relay codebase for all three.** B and C run the same `relay.py` as A, with `--push`. In B the relay is the "Python control service"; its own GET/events go unused.

## How to run

```
cd box/gateway-do && scripts/up.sh          # DEADLINE_S=1200 IDLE_S=300; prints A/B/C URLs (~40 s)
cd box && uv run --extra dev python -m box.gateway.scenarios --provider modal \
  --gw A=http://localhost:8780 --gw B=https://box-gateway-do.chiraagbalu.workers.dev/b \
  --gw C=https://box-gateway-do.chiraagbalu.workers.dev/c --run live --out gateway-do/results/live.json
DEADLINE_S=180 IDLE_S=60 gateway-do/scripts/up.sh   # then --run deadline
... --run latency                                   # one T4 per variant
uv run python -m box.gateway.compare                # the table
cd box/gateway-do && scripts/down.sh
# the page: blogs/verify_connect.py --gateway https://box-gateway-do.chiraagbalu.workers.dev/{b,c} (MODAL_TOKEN_ID/SECRET)
# no cloud: npx wrangler dev --port 8797 & BOX_PUSH_SECRET=$(cat .push-secret) uv run --extra dev python -m box.gateway.local_stack
```

## Results (Modal, region us, CPU sandboxes except (7) = T4; variants run in parallel)

| scenario | A relay | B do-owns | C fanout |
|---|---|---|---|
| (1) machine killed: reader's stream shows | ended(machine_lost) after 10.2 s | ended(machine_lost) after 22.5 s | only a step ('machine silent') after 20.0 s |
| (1) GET after the kill | 200 machine_lost | 200 machine_lost | 200 machine_lost |
| (1) logs survive (fresh tab replays the mid-run lines) | 8/4 | 4/4 | 4/4 |
| (1) recovery: new session connect (CPU) | 3.2 s | 4.8 s | 6.1 s |
| (2) reattach (Last-Event-ID): first event | 406 ms, repeats 0 | 68 ms, repeats 0 | 63 ms, repeats 0 |
| (2) reload (no id): full replay | 361 ms | 49 ms | 53 ms |
| (2) GET /sessions/{id} p50 | 404 ms | 49 ms | 622 ms |
| (3) two tabs: same lines, same order | True/True | True/True | True/True |
| (3) machine log line -> tab, p50 / max | 1473 / 2377 ms | 460 / 592 ms * | 210 / 359 ms |
| (4) left alone (idle 60 s) | idle at +59.2 s | idle at +57.7 s | idle at +59.0 s |
| (4) kernel held open (deadline 180 s) | deadline, 0.9 s late | deadline, 1.5 s late | deadline, 0.9 s late |
| (6) code over the box SDK (non-blank, non-comment lines) | 604 | 1303 | 1180 |
| (7) connect T4 (POST -> running) | 5.6 s | 7.1 s | 7.6 s |
| (7) first cell (kernel start + nvidia-smi) | 3.74 s | 6.08 s | 5.04 s |
| (7) cell RTT p50 / p90 | 78 / 81 ms | 89 / 94 ms | 80 / 84 ms |
| (7) end (POST /end -> ended) | 2.1 s | 2.3 s | 2.4 s |
| page proof (verify_connect.py, T4) | (relay agent's runs) | pass | pass |

How to read the rows:

- **(1)** "8/4" for A: A's fresh tab replays from the relay's session record (`record=`, a Modal Volume), which holds lines the machine wrote that the 2 s poll had not streamed before the kill. B and C replay what the DO already got. All three answer GET with `machine_lost`; C's answer comes from the relay. On the stream, C only says "silent": it does not decide an end. The page still ends correctly, because its kernel websocket drops and it re-GETs. A took 10.2 s here; the run before the relay gained `record=` saw it in 0.7 s (cause not investigated).
- **(2)/(3)** A's stream polls the machine every 2 s, which explains A's 1.5 s log latency and ~400 ms resumes. B and C push: the forwarder reads every 0.2 s and POSTs to the DO.
  - \* B and C run the same log path. The killed second run measured B 183 ms and C 171 ms.
  - B's offset estimate went through its DO proxy and read +0.18 s, against -0.04 s for the direct paths. Corrected, B is ~235 ms, the same as C. So the gap in this row is the measurement, not B.
  - C's GET is slow (622 ms) because the Worker forwards it through a quick tunnel to the relay, which asks Modal. B's GET is answered from the DO.
- **(4)** Who enforces:
  - Idle is the machine's supervisor in all three. The DO can't see a spliced websocket close.
  - The deadline is the supervisor in A and C, and the DO alarm in B: the step `deadline reached (this gateway's alarm)`, then the relay ends the machine. B's supervisor deadline is the DO's plus 120 s, as a backstop.
- **(5) Token location:**
  - A: the browser holds the token and sends it on every call. The relay keeps it only for a request or the boot thread, plus a sha256 digest.
  - C: as A. The Worker passes the token through. The DO keeps only a digest. The derived Jupyter token sits in the DO ring, inside the running status.
  - B: the DO stores the reader's Modal `{id, secret}` in SQLite from create until the end (`setEnded` deletes it), plus Jupyter's token. The browser gets a DO-minted kernel token instead.
  - All three: the machine's spec.json holds the Jupyter token and, for B/C, the push key. With `record=` these are copied to the reader's own `box-sessions` volume.
- **(6) Stateful components and deploy:**
  - A: the machine is the only authority. Deploy = one Python process.
  - C: the machine is the authority; the DO is a cache (lose it and only replay is lost). Deploy = A's relay reachable by the Worker, plus a Worker, a SQLite DO, a secret, and machine egress to workers.dev.
  - B: two authorities, the DO and the machine (idle, backstop). Same deploy as C.
  - B/C add 699/576 code lines over A. The shared 561 are push.py, forwarder.py and the Worker base.
- **(7)** Cost: the gateway adds nothing measurable (Workers free plan; DO duration only on paid plans). Machine time per T4 session was 24-28 s ≈ $0.004-0.005.

## Found while measuring

1. **B's end reason raced (fixed).** While the DO alarm awaited the relay's `/end`, the forwarder's own "ended(stopped)" push arrived. A DO's input gates allow that during an `await fetch`. The session ended `stopped` instead of `deadline`. Fix: the DO writes `ending=<reason>` before the call, and an end the machine reports meanwhile takes that reason. Rerun: `deadline`. The first run is kept as `B_first_run_race` in deadline.json.
2. **B's proxied kernel websockets can pin a machine past idle (not fixed).** I killed a harness run mid-flight. A's and C's orphan sessions idled out at 5 min. B's did not: two connections from Modal's tunnel to :8888 stayed established, so the supervisor never saw it idle. Cloudflare kept the upstream half of the spliced socket open after the client vanished. B's DO deadline alarm reaped it at 20 min, exactly on time. n=1, from an abrupt client death. A closed browser tab sends a close frame and may behave fine; untested.
3. **workers.dev answers Python's default User-Agent with 403 (error 1010).** The forwarder, push.py and the harness now send their own UA. Anything else pushing from Python will hit this.
4. **A's GET says "booting" for a moment after an end.** Between the supervisor killing Jupyter and writing ended.json, the relay sees a live supervisor whose Jupyter doesn't answer. That window is ~1 s, longer with a forwarder. `test_push.py` waits it out. Worth a look in relay.py (`machine_status`).

## Recommendation (the orchestrator decides)

**Default the demo to A.** It is the smallest (604 lines, one process). It matches the decided principles: one owner, no token at rest outside the browser, fail-stop. With `record=` it already answers "machine_lost" and replays logs after a death. Its weak spots don't touch the demo: 1.5 s machine-log latency and ~400 ms resume. Cell output goes over the kernel websocket, not SSE, and boot steps stream from memory.

**C is the upgrade if live log tailing or many readers matter.** It gets ~200 ms log latency and ~60 ms replay without moving authority, and its DO is a disposable cache. The cost is a Worker, a secret, and a public relay URL. For dev that URL is a quick tunnel, and quick tunnels were the flakiest part of tonight (see papercuts).

**B hasn't earned its place.** It works: the page passes, the DO deadline is precise, and GET is the fastest. But it puts the reader's Modal token at rest in Cloudflare and splits authority between the DO and the supervisor, which produced finding 1. It also leaks idle sessions until the DO deadline (finding 2). The one thing only B does is enforce a deadline without the machine. The supervisor already does that, to the second.

## Judgement calls

- The machine pushes through a **forwarder service** rather than the supervisor. Supervisor push would be the principled version, but `supervisor.py` was mid-merge on two branches. The forwarder gets the session's reason from Jupyter's `status.json`: the supervisor kills services in start order and writes the reason there before it SIGTERMs the forwarder. This works, but it couples to that ordering.
- **One Worker, two prefixes** (`/b`, `/c`) and **three relay processes** (A; C's; B's with a later supervisor deadline). B's DO owns a 1200 s deadline; its supervisor gets 1320 s.
- **Worker deployed to workers.dev**; relays local behind cloudflared quick tunnels, which carry only Worker -> relay POST/GET, never SSE. Readers and machines talk to workers.dev.
- **B verifies X-Box-Token** on GET/end/events against a digest, although the contract says "B ignores". C does the same for events, so a session id alone can't read its log.
- **C passes the running status, Jupyter token included, through its ring.** The page needs `kernel` in the SSE status, and C has no kernel of its own to hand out.
- **Spike tests removed**: `test/*.mjs` and `demo-curl.sh` tested routes that no longer exist. Their results moved to `results/spike/`. The harness plus `test_push.py` replace them.
- **Deadline and latency runs merged by hand.** B's deadline was rerun after the fix. B's and C's latency were rerun because their first try hit the Worker before the fresh tunnels resolved on Cloudflare's side. Both are noted inside the JSON.
- **Not merged with box/reader-path directly.** box/relay was rebased onto it, and I merged box/relay twice (last: the `record=` commits, conflict in `modal_config` resolved to `Access` + `push`).

## Uncertainties

- Single runs. Only the log-latency row has a second sample: the killed run gave A 1966, B 183, C 171 ms.
- Finding 2 needs a browser-tab test: close the tab vs kill the network.
- Cross-clock latency uses an NTP-style offset taken from one kernel round trip (±RTT/2). It is wrong through B's proxy (see \*).
- DO placement wasn't controlled. The DOs live near whoever touched them first, the relay or the Worker from this laptop's colo.

## Papercuts

- Quick tunnels: a new hostname resolves on this laptop before it does inside Workers. One run failed with HTML error pages; `up.sh` now waits on the Worker's view. A relay 502 through a tunnel comes back as Cloudflare's HTML 502 page.
- Python's `requests.iter_lines` holds SSE events until 512 bytes arrive, which skewed the first latency numbers. The harness uses `http.client` + `read1`. Closing a blocked stream needed `socket.shutdown`, because the relay ends an SSE response without closing the keep-alive connection, so there is no EOF.
- `pkill`-ing a harness run orphans its sessions. They self-reap (idle; B by deadline), but it cost ~25 min of CPU sandbox.

## Spend (Modal, arb8020)

T4: 5 sessions (3 latency runs × ~25 s, 2 page proofs × ~2 min). CPU: ~30 sessions, ~1.5 h of sandbox time in total, the longest being B's 20 min orphan. Estimate < $0.15 at list prices, against a $2 cap. All sandboxes swept: 0 live with `box.purpose=reader-path-dev` at the end.
