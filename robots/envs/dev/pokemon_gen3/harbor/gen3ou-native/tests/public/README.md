# Public verifier slice

The current runnable verifier exercises a six-point build/API packaging slice:

- canonical `gen3_abi.c/.h` and thin Ocean adapter are present;
- strict native shared-library build succeeds;
- checked native ABI, scheduler, effect, hit, move-program, and Ocean tests pass;
- the resulting shared library has no Node, Python, or Showdown dependency.

All other score sections are emitted as zero. Canonical cases are parameterized
by `case.schema.json` and `TEST_PARAMETERIZATION.md`. The first shared case has
an executable boundary differential runner and agrees at two request
boundaries; translated Showdown-focused cases and the remaining semantic
boundary projections are still required before semantic points can be awarded.

The separate verifier also runs two non-scoring integrity checks:

- a deterministic smoke of the pinned, observation-only Showdown handler/PRNG
  trace patch;
- JSON Schema plus referential/mapping validation of the frozen feature map;
- verifier-owned JSON Schema and closed-reference validation of each canonical
  differential case before its oracle or native projection is used.

The latter currently reports the deliberately unfinished required mappings in
`score.json`; self-reported manifest status never awards coverage.
