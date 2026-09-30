# Ocean performance calibration

This verifier-side harness measures the production `ocean/pokemon_slice.h`
surface and native `PokemonBattle` kernel under the protocol in
`harbor/gen3ou-native/GRADER_CONTRACT.md`. It is
an optimized (`-O3`), trace-disabled scalar C loop over 1,024 independently
seeded environments. It performs 64 warm-up sweeps followed by five measured
repetitions of 256 sweeps each.

```sh
make -C verify/performance clean run
make -C verify/performance self-check
make -C verify/performance gate
make -C verify/performance container-gate
make -C verify/performance reference-gate
```

Each environment follows a deterministic rank within its current legal action
mask, including moves, switches, forced replacements, and wait requests, and
resets after a terminal transition. The default 2v2 teams are intentionally a
hot-path calibration, not evidence for complete mechanic coverage. The JSON
reports scalar and 1,024-environment batch rates, p99 batch-sweep latency,
deterministic digests, exact sizes for the Ocean environment and major native
state types, verifier buffer bytes, and incremental resident bytes per
initialized environment. The executable also
runs the same small workload twice before calibration and asserts identical
digests. `make self-check` independently runs the complete workload twice and
compares its output digest.

RSS is sampled using `mach_task_basic_info` on macOS and `/proc/self/statm` on
Linux. Verifier-owned environment and I/O arrays are allocated and touched
before the RSS baseline; incremental RSS therefore measures native battle
allocations and allocator/page overhead, while their exact static sizes are
reported separately. RSS resolution and allocator behavior make this a batch
estimate, not an exact allocation-accounting result.

The contract's 100,000 boundaries/s, 25 ms p99, and 128 KiB incremental RSS
figures are provisional until calibrated and frozen on the final Harbor image.
This harness reports evidence and intentionally does not encode those values as
portable pass/fail thresholds. The required 0.8x reference comparison remains
unavailable until the verifier-owned reference interpreter and final Harbor
CPU image exist.

`orbstack-gcc14-calibration.json` retains the current Linux/GCC 14 calibration
against the exact `gcc:14-bookworm` image digest. It records both the original
quiet-host sample and a later contention sample from the same image and
workload. Across those observations, batch medians ranged from 17,638 to 22,948
boundaries/s and p99 sweep latency ranged from 58 to 126 ms. The executable
candidate floor is therefore 15,000 boundaries/s, 150 ms p99, and 128 KiB
incremental RSS per environment: a regression tripwire below the observed
range rather than a claim about dedicated-worker latency. The deterministic
digest matches the native macOS run. This honestly invalidates the guessed
100,000/25 ms absolute thresholds;
the candidate still must be reproduced unchanged on the final Harbor worker,
where the relative-reference requirement can also be measured.
`make gate` enforces only that retained candidate calibration and rejects a
changed workload digest. The measured candidate median is not a reference
measurement: treating the implementation as its own reference would make the
0.8x check circular.

`make container-gate` is the serialized Checkpoint 7 gate. It runs `gate`
inside the exact digest-pinned GCC 14 image used for the retained calibration,
so host scheduler and compiler differences cannot be mistaken for a candidate
regression. Docker or an OCI-compatible Docker socket is verifier-only; it is
not a runtime dependency of the submitted environment.

`reference-contract.json` records the separate verifier-owned reference
obligation. `make reference-gate` deliberately fails while that contract is
pending. It becomes executable only after the final Harbor environment and an
independently identified reference implementation have supplied a frozen
median for the same workload, environment count, and output digest. The
checker rejects a reference bearing the candidate implementation identity.
