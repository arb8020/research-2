# Obtainability language spike decision

Decision: keep the production implementation in C. The obtainability slice is
now frozen for this comparison; no candidate demonstrates a substantial
reduction in total semantic complexity while preserving the existing build and
ABI constraints.

The compared slice is the cold admission provenance interpreter, not a toy
battle: fixed-capacity `L/M/T/E/S/R` source intersection, lineage, Sketch,
event witnesses, egg and chain breeding, underlevel event exceptions, Hidden
Power normalization, plugin validation, and atomic normalized-set publication.
The production C boundary is `pokemon_admission.c` orchestration plus the pure
`pokemon_acquisition.c/.h` solver over generated immutable tables.

| Candidate | Exact evidence | Handwritten size | ABI/build result | Decision |
|---|---:|---:|---|---|
| C baseline | 136/136 pinned-oracle cases; deterministic replay | acquisition: fixed-capacity C module | existing C11 build and ABI | retain |
| Rust | 15/15 shared basis; focused field/plugin tests; C link smoke | 453 runtime lines | fixed check path, but 17 MiB archive and a generated-schema bridge | no migration |
| Zig | 102/102 byte-exact against its frozen C snapshot | 232 Zig vs 412 snapshot-C lines | small binary delta, but `@cImport` preserves the same pointer/integer illegal states and adds toolchain/debug complexity | no migration |
| C-style C++ | 96/96 pinned-oracle snapshot; replay and ASan/UBSan exact | 1,463 implementation + 425 header lines | generated C is not strict-C++ aggregate-compatible; requires a mixed C/C++ build | no migration |

The fixture totals differ because the spikes were deliberately isolated while
the integration owner continued closing the slice. A candidate gets credit
only for the frozen corpus it copied; none may claim the final 136-case gate.
Their performance measurements are directional only: Rust measured about 574
ns/check, Zig's process-level comparison was dominated by startup and JSON,
and C++ was within benchmark noise of C. None demonstrates a material Ocean
throughput gain.

Rust provides the clearest local sum types, and Zig provides the smallest
prototype. Those local gains do not remove the generated-data contract,
Showdown-source semantics, C ABI, or verification surface that dominate this
slice. C++ adds no useful illegal-state compression under the required C-style
subset. Migration would therefore add language and schema boundaries without
enough semantic compression.

The isolated evidence remains outside the integration tree:

- `/tmp/pokemon-obtainability-rust-spike/REPORT.md`
- `/tmp/pokemon-obtainability-zig-spike/README.md`
- `/tmp/pokemon-obtainability-cpp-spike/README.md`

Reconsideration requires exact agreement through the current native admission
driver, complete malformed-bundle and transaction proofs, an unchanged C ABI,
and a measured improvement large enough to pay for a second toolchain and
generated-schema boundary.
