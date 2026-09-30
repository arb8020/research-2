# Deterministic randomized admission verification

This verifier extends the curated admission corpus with a bounded,
deterministic source-recombination batch. Five fixed LCG seeds each generate
125 Showdown-accepted teams and 125 teams rejected specifically by
`obtainablemoves`. Team sizes, species, move counts, move order, source
combinations, level, gender, nature, shininess, IVs, EV spreads, held-item
presence, and the position of the first source-invalid member vary. The
generator asserts coverage of every declared value family before emitting the
1,250-case artifact.

The pinned Showdown `TeamValidator` labels each generated team. The native
runner independently reports `BANNED` or `INCOMPLETE`, the native rule and
team member, and normalized species. `INCOMPLETE` is intentional: acceptance
by the implemented admission checks is not a claim that the native runtime
implements all of Showdown legality.

Generation, oracle output, and native output are each replayed exactly. A
structured mismatch records the first differing field. On failure, the
verifier retains a causal team prefix, removes irrelevant members and moves
only while the same mismatch reproduces twice, and atomically writes
`case.json` plus `failure.json`. Existing failure artifacts are never
overwritten.

The gate also checks `../randomized-obtainability-report.json` byte-for-byte.
That report contains the manifest, achieved coverage dimensions, result counts,
and fixture/oracle/native digests. Regenerate it deliberately with
`POKEMON_ADMISSION_UPDATE_REPORT=1`; an unproducible historical report is not
accepted as classification evidence.

Run:

```sh
node verify/admission/random/test.js
node verify/admission/random/run.js /path/to/clean/pinned/showdown
```

The generator is deliberately bounded and curated. It proves agreement over
the generated source-recombination distribution; it does not claim exhaustive
team legality, exhaustive acquisition reachability, or full native legality.
