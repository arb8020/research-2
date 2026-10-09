# Archive: who owns a reader's session (A vs B vs C)

Decision 3 in `box/DECISIONS-reader-path.md` compared three answers, all speaking `box/CONTRACT-gateway.md`:

- **A relay**: the machine (its supervisor) owns the session. A stateless Python relay over the box SDK.
- **C fanout**: as A, plus a Cloudflare Durable Object in front that only fans events out.
- **B do-owns**: a Durable Object owns the session (status, deadline, the reader's token, a kernel proxy) and calls the relay to make and end machines.

**A was chosen.** It lives on as `box/gateway/relay.py`; the `--push` seam B and C needed was removed from it.
The evidence (live, deadline and latency runs on Modal, code weight, the recommendation) is in
`gateway-do/COMPARISON.md`, with raw results in `gateway-do/results/`.

What is here:

```
gateway-do/     # the Worker + Durable Objects for B and C, COMPARISON.md, results/, scripts/
push.py         # was box/gateway/push.py: the relay's sender to the fan-out
forwarder.py    # was box/gateway/forwarder.py: on-machine service that pushed Jupyter's log
scenarios.py    # was box/gateway/scenarios.py: the A/B/C harness
compare.py      # was box/gateway/compare.py: static facts + results -> comparison.json
local_stack.py  # was box/gateway/local_stack.py: A/B/C relays on the local provider
test_push.py    # was box/tests/test_push.py
```

This is a record, not code. It is not maintained, nothing live imports it, and pytest does not collect it
(`norecursedirs` in `box/pyproject.toml`, and `archive/conftest.py`). It no longer runs as is: paths
inside it (including in COMPARISON.md) are the pre-archive ones, and `relay --push` is gone.
