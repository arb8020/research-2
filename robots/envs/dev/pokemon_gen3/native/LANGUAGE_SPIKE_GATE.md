# Kernel language spike gate

Mechanics are frozen for this comparison. Rust, Zig, and C-style C++ must each
implement the same party-order/delegation slice through the existing C ABI;
they may not change observable support claims, fixture normalization, generated
Gen 3 data, fixed capacities, or PRNG labels.

## Frozen semantic basis

Pinned oracle revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

| Fixture | SHA-256 |
|---|---|
| `beat-up-party-order.json` | `db469046fbc6dead278e7a620112651a0939015f73f0ebe5b43484ce38da22c9` |
| `beat-up-status-filter.json` | `acd9eb8c7a9e806c39319eda2b99b0e6489755cad95bac02123cae42d0fc8397` |
| `beat-up-typeless-ghost.json` | `07f48a99faf6f92e65b9ce44bed29a548a37390883982e3911c4625fc0feeaa4` |
| `beat-up-zero-contributors.json` | `90603dcba70798d280ac98e9cb297fc89661dad348534e489a74defaadae6269` |
| `assist-metronome-party-order-duplicate-weight.json` | `e92df3f1d02fa2845af6684ef9e49741a3d7ad967bd1488d55ce357dd6dad93f` |
| `assist-metronome-empty-noassist-pool.json` | `e25c1e61a0fde5c2c68d4b42314d891aaf9b310c7b8298f41f6dc3e15e03d449` |

The basis is 18 exact request-to-request boundaries. It covers mutable party
permutation, aborted and committed switches, Beat Up ordering/filtering/
typelessness/zero contributors, Assist ordering/duplicates/eligibility/empty
pool, nested Metronome delegation, labeled PRNG, and replay.

## Constraints

- Export the existing C ABI and retain fixed-capacity, caller-owned state.
- Allocate no memory after initialization and require no language runtime at
  deployment.
- Consume immutable generated plugin data; do not branch on move names or IDs.
- Reject incomplete or mismatched plugins before mutation or PRNG consumption.
- Match all 18 boundaries exactly and replay byte-for-byte deterministically.
- Supply focused tests and sanitizer or language-equivalent checks.

## Measurements

Record handwritten semantic LOC, cross-module declarations, build command and
clean build time, stripped binary size and dynamic dependencies, state size,
peak RSS, and median/p95 nanoseconds per step plus battles/second at batch sizes
1, 64, and 1024. Report how choice, action, hit-result, handler, and plugin
types exclude illegal states and how mutation ownership is localized.

## Decision rule

Any fixture mismatch, ABI/capacity change, post-init allocation, runtime
dependency, missing memory-safety gate, move-ID dispatch, or performance loss
over 10% is a veto. A candidate qualifies for migration only with performance
within 5% and binary size within 25%, plus either:

- at least 25% less handwritten semantic LOC; or
- at least 15% less LOC, two concrete illegal states made unrepresentable, and
  at least 30% fewer cross-module declarations.

Qualification permits a migration proposal, not an automatic rewrite.
