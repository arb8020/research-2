# Independent pinned-Showdown regression audit (v2)

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

Audit date: 2026-09-28

This is an independent check of the regression-map proof boundary. It is not a
feature-support claim and it does not change `descriptor-map.json` or any
classification. The canonical per-test artifact is
`gen3ou-unified-regression-map.json`; this note records how its denominator and
evidence state were challenged.

## Result

The checked map has a defensible, reproducible denominator for the pinned
Showdown suite:

| Proof boundary | Result |
| --- | ---: |
| Static `it()` / `test()` declarations below `test/sim` | 1,976 |
| Active / pending static declarations | 1,933 / 43 |
| Canonical / overlay-adjudicated declarations | 1,053 / 923 |
| Mocha-registered instances | 2,172 |
| Active / pending registered instances | 2,129 / 43 |
| Runtime instances beyond lexical declarations | 196 |
| Explicit-Gen-3 declarations independently found and mapped | 31 |
| Applicable static Gen 3 OU assertions | 261 |
| Applicable loop-expanded variants | 41 |
| Applicable static assertions with assertion-specific evidence | 164 |
| Applicable static assertions still requiring an exact case | 97 |

All six independent validators passed against the pinned checkout:

```text
validate-unified-regression-map.js
validate-all-test-census.js
validate-runtime-registration-census.js
test-runtime-registration-contract.js
validate-semantic-map.js --require-complete
audit-explicit-gen3-completeness.js
```

The runtime census is important: source-AST enumeration alone undercounts 196
loop-expanded tests. The companion runtime artifact preserves all 41 applicable
Gen 3 OU variants (eight Rollout/Ice Ball and 33 trapping variants) rather than
letting one loop declaration stand in for every parameter value.

## Enumeration and adjudication method

1. Parse every pinned `test/sim/**/*.js` file and key every lexical `it()` or
   `test()` declaration by file and source line, including skipped tests.
2. Join every declaration to either the reviewed canonical partitions or an
   explicit whole-suite overlay. Reject a missing key, duplicate key, stale
   line, or oracle-revision mismatch.
3. Independently execute Mocha's registration phase and reconcile registered
   test names with the static census. Preserve each relevant loop value.
4. Independently scan names, enclosing suites, and bodies for explicit Gen 3
   selection. This catches declarations outside filename/entity heuristics.
5. Resolve the Gen 3 move/ability/item test-file closure from pinned Showdown's
   resolved Dex rather than trusting the native inventory. This is the check
   that prevents a missing native inventory record from erasing its upstream
   tests.
6. For every applicable assertion, require mechanics, semantic boundaries,
   authoritative Showdown sources, four explicit evidence categories (native
   unit, differential, invariant, randomized), and either assertion-specific
   evidence or a named required case.

Modern default-generation tests are not automatically Gen 3 evidence. They
become portable only after the resolved Gen 3 source proves the same semantic
assertion. Doubles/FFA, post-Gen-3 mechanics, parser-protocol behavior, and
team-legality behavior retain explicit non-runtime dispositions with evidence.

## Independent findings

### The map is structurally complete, not implementation-complete

The current 261 applicable static assertions include 164 assertion-specific
rows and 97 still requiring exact cases. The original Checkpoint 7
reconciliation divided those open rows into stale mappings, genuine gaps, and
semantic-inspection debt; see `CHECKPOINT7_RECONCILIATION.md`. Some cases
intentionally close several assertions. No passing upstream test is
used by itself to promote a supported feature.

### Post-Gen-3 ability transposition is now explicit

An independent review challenged all 411 rows previously excluded solely from
their ability owner's introduction generation. The enforced result is 15 legal
Gen 3 alias obligations, 15 shared-operation-but-not-equivalent assertions, and
381 owner-specific terminal assertions. The 15 aliases cover Transform,
Magic Coat, Thief/Covet, Rain Dish, Water Absorb, Immunity, Lightning Rod, and
Skill Swap boundaries. Their future ability owners remain unsupported and
unreachable; only the explicitly named Gen 3 denotation enters the required-case
queue. The checked exception table is keyed by exact source identity, and its
validator rejects stale, missing, or newly unmatched rows.

### Highest-value direct Gen 3 gaps

The direct tests make several false-positive coverage risks concrete:

- Quick Claw activation is covered, but unequal natural speeds becoming the
  same priority/speed bracket and consuming the labeled tie draw still needs
  `quick-claw-induced-speed-tie`.
- Sitrus consumption is covered, but status residual crossing the threshold
  and deferring consumption until the following residual pass still needs
  `sitrus-status-residual-deferral`.
- Glare's ordinary paralysis path is covered, but its Gen 3 natural type
  immunity needs `glare-gen3-natural-immunity`.
- Thick Fat's base-power modifier exists, but composition with Charcoal or
  Never-Melt Ice needs `thick-fat-type-item-composition`.
- Haze's boost reset exists, but preserving Focus Energy needs
  `haze-preserves-focus-energy`.

Weather Ball's four Counter/Mirror Coat assertions, Pursuit's continued switch,
Gen 3 faint-order termination, and delegated OHKO behavior have
assertion-specific differential evidence in the current machine map.

### Newly implemented mechanics need map refresh, not automatic promotion

The working kernel and fixture tree contain newer Flash Fire, Fury Cutter, and
Truant evidence than some canonical records acknowledge. In particular, the
map still lists the five inherited Truant assertions with no evidence and named
cases, and retains entity-level scope for the explicit Flash Fire and Fury
Cutter tests despite closely named focused/differential artifacts. This is not
proof that those assertions are closed: each scenario must be inspected for an
exact semantic match, then the map regenerated and validated. Do not infer
coverage from filename similarity.

### Admission is a separate proof obligation

Pinned breeding/form/team-validator tests contain Gen 3 OU legality assertions,
but learnset obtainability, event provenance, Pomeg Glitch legality, and forme
validation are not battle-state transitions. They belong in a distinct native
admission/verifier map. Battle differential success cannot prove them.

### Delayed actions require source-transposed tests

Future Sight and Wish upstream tests mostly execute later generations, so their
modern numeric and modifier expectations are not Gen 3 oracles. Their scenario
shapes remain valuable after source adjudication: duplicate slot rejection,
slot ownership across switching, expiry through empty/fainted slots, Protect
bypass, cast-versus-expiry state, PRNG staging, forced replacement, and winner
resolution. The current map correctly treats this as source-transposed evidence
rather than copying TypeScript expectations.

## Hygiene and known documentation debt

- `verify/inventory/gen3-source-applicable.tsv` is an untracked, older heuristic
  census (548 assertions plus header). It is superseded by the reviewed unified
  map and is a cleanup candidate once no active work consumes it.
- The Truant map refresh closes five exact upstream assertions. The machine
  artifact and passing validators remain authoritative when later evidence
  changes these counts.
- These counts describe the working-tree snapshot audited above. Any change to
  upstream revision, semantic overlays, fixtures, or native test symbols must
  rerun the complete validator set.

## Porting rule

Port the semantic assertion and legal scenario, never the TypeScript test body.
Use differential fixtures for choices, queues, event order, phase/request
transitions, canonical state, labeled PRNG, switching/fainting, and terminal
results. Use focused C tests for internal invariants or deliberately constructed
states unreachable in legal Gen 3 OU. Update feature support only after source
mapping, native boundary, focused proof, differential evidence, and the pinned
revision all agree.
