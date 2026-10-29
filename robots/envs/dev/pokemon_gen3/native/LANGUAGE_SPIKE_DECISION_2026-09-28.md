# Party/delegation language spike decision

Decision: continue the C kernel. None of the three isolated candidates clears
the frozen migration gate in `LANGUAGE_SPIKE_GATE.md`.

The production baseline retains the active `pokemon_battle_init`,
`pokemon_battle_request`, `pokemon_battle_step`, and `pokemon_battle_view` ABI,
a 26,688-byte caller-owned `PokemonBattle`, fixed capacities, and exact replay
of all 2,982 differential boundaries. The frozen party/delegation subset is 18
boundaries across six checksum-locked fixtures.

| Candidate | Isolated commit | Useful evidence | Gate result |
|---|---|---|---|
| C-style C++ | `93c55837` | 329 production LOC; 500-byte reduced state; focused + ASan/UBSan pass | **veto**: private ABI, no 18-boundary proof, links `libc++` |
| Zig | `c39695c7` | 273 LOC including tests; 744-byte reduced state; 6/6 + ReleaseSafe pass; only `libSystem` dynamically linked | **veto**: private ABI and no active view/trace or 18-boundary proof |
| Rust | `c5429b18` | 602 production LOC; 752-byte reduced state; 6/6, Clippy, allocation-free `no_std` build | **veto**: private ABI, no active view/trace or 18-boundary proof, no Miri/sanitizer |

All three use clearer sum types for normalized choices and hit results, and all
three keep plugin validation before mutation and PRNG consumption. Those are
real local design advantages. They do not demonstrate lower complexity for the
actual kernel: each omits the canonical state, requests, handler/event traces,
rollback surface, and the observer comparison that dominate the implementation.

The reported microbenchmarks measure reduced transitions and are intentionally
not compared with full `pokemon_battle_step`. C++ reported roughly 2.3 ns,
Zig 14--41 ns, and Rust 11--15 ns per reduced operation depending on batch;
none includes production view or trace construction. Therefore the performance
and binary-size qualification thresholds remain unproven rather than passed.

No candidate is merged. Their estimates for a decision-quality active-ABI rung
are 1--3 engineer-weeks, followed by roughly 6--12 weeks for migration plus
dual-run soak. Reconsideration requires one candidate to implement the unchanged
active ABI and match the six fixtures through the existing differential driver,
not another reduced private kernel.
