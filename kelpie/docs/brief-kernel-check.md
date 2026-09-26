# Brief: the kernel check layer (hand-rolled; popcorn and crucible as references)

Date: 2026-09-09. Ruling: popcorn (tilde-research/popcorn, /tmp/popcorn-survey) is a reference, not a dependency; crucible's `verification/kernels/correctness.py` is the same self-budgeting rule already ported ("popcorn-style" per crucible's verifier.md). Define the check functions WITH THE USER first (matklad: one check per boundary/rung); this brief is the survey result, not a launch order.

## Reuse as-is (crucible, crucible/verification/kernels/)
- `correctness.py` (157 LoC): `error_budget(truth, ref) = max(2*||ref-truth||_inf, FLOOR[dtype]*||truth||_inf)`, floors fp32 2e-5 / fp16 1e-3 / bf16 2e-2; `zip_leaves` structural compare over nested outputs; `Tolerance = Exact|Budget|Fixed`.
- `cases.py` (25): `CaseSet(graded, probes)`.
- Skip `timing.py` (837, subprocess isolation + Dieselgate recheck) unless we check untrusted code.

## Copy the idea (popcorn, src/popcorn/bench/)
- `compare.py`: three-way compare (reference in fp64 = truth; reference at native dtype = budget; candidate), `Gauge.verdict` pass iff `err <= max(2*budget, floor*scale)`; status taxonomy pass/fail/oom/error/crash; cotangent grad check for backward.
- `grid.py`: cases sampled from a shape grammar on the reference signature (jaxtyping strings), adversarial seeds (tile+-1, pow2), auto-repair for illegal combos (GQA divisibility, MoE top_k, RoPE half-dim).
- `core/fingerprint.py`: source-hash fingerprint invalidates recorded results.

## What neither has (kelpie must build)
- Paged-KV cases: block tables, slot mapping, seq_lens, per-request plans (a case is a batch of variable-length requests).
- Stepped/recurrent kernels: state threaded across steps, budget per step.
- Spec-decode accept: accepted prefix == target greedy; accept rate.

## Candidate signatures (~500 LoC total)
    check_kernel(op, impl, cases, *, backward=False) -> Verdict     # error_budget + zip_leaves; grad via cotangents
    check_paged(op, impl, cases: CaseSet[PagedCase]) -> Verdict     # PagedCase carries block_table/seq_lens/page_size
    check_stepped(op, impl, init_state, steps) -> Verdict           # per-step budget vs fp64 oracle
    check_spec_decode(draft, target, cases) -> Verdict
    check_forward(model, case) / check_step(plan) / check_run(prompt) / check_serve(request_json)   # per ladder rung
