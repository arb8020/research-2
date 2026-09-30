# Checkpoint 7 verification reconciliation

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is the live work-selection boundary for Showdown verification parity. It
does not promote feature support: Checkpoint 6 owns that classification. It
asks whether every applicable upstream assertion has evidence for that exact
assertion rather than merely evidence for the same descriptor.

## Denominators

The pinned suite has 1,976 static declarations and 2,172 Mocha-registered test
instances. Semantic adjudication leaves 248 applicable static Gen 3 OU
assertions. The separate runtime map has 281 applicable instances because it
preserves loop expansion. These denominators must not be conflated.

At the start of Checkpoint 7, 82 applicable static assertions were
assertion-specific and 201 required cases. Independent reconciliation divided
the 201 into:

- 120 likely stale mappings with current candidate evidence;
- 63 genuine missing scenarios;
- 18 assertions requiring closer semantic inspection.

“Likely stale” is not a promotion. Each row is closed only after its exact
upstream assertion is compared with the named focused test or differential
fixture and the generated maps validate.

The first reviewed batches close five Endless Battle Clause assertions, three
Flash Fire assertions, one Fury Cutter assertion, two Belly Drum assertions,
three Counter assertions, nine PRNG assertions, and eighteen strictly matched
stale-ledger assertions across Brick Break, choice control, Fake Out, team
cure, jump-kick failure, recharge, item mutation, Pursuit, atomic formulas,
and Substitute, followed by exact Ingrain, Taunt, item-transfer, Yawn, and
trapping-lifecycle and typed-choice matches. The authoritative generated map now
reports 246 applicable static assertions with assertion-specific evidence and
none requiring a case. The runtime map reports 304 assertion-specific instances
and none requiring a case; loop-expanded trapping cases account for the larger runtime
increase.

## Genuine-gap clusters

The Team Validator Pomeg Glitch Clause gap is closed by a typed
admission-format policy and an exact stock-reject/custom-format-accept pair;
it does not enter the battle kernel. Every applicable static assertion now has
exact native or differential evidence.

The PRNG and choice/request batches precede claims about randomized full-battle
reproducibility. Admission remains independent of battle-kernel work.

## Full-battle runner boundary

Do not revive `harness/diff.py`; it targets the obsolete `engine/gen3_abi`
surface. The new runner should generate legal six-member `gen3ou` traces from
pinned Showdown, with a policy PRNG independent of battle PRNG, and emit the
ordinary differential case schema. Existing `verify/slice` compilation,
oracle, native projection, comparison, and replay remain the sole semantic
comparison path.

Showdown is the action authority. At each decision it emits normalized legal
choices, a deterministic policy selects one, and the resulting complete trace
is replayed by both engines. A cap is a failure artifact, not a successful
battle. Batch compilation is required so randomized verification does not
compile once per battle.

The first deterministic balanced-team run terminates naturally after 223
decisions and exposes 224 oracle boundaries. Expanding the executable species
table from the old 89-species fixture prefix to the complete frozen 369-species
inventory removed the first dishonest compilation boundary. All 224 boundaries
now agree exactly and repeat byte-for-byte. That run exposed and closed three
generic errors: side-target moves discovering target-owned `TryHit` handlers,
residual discovery grouping owners instead of preserving Showdown's per-active
order, and stalling-guard admission occurring after unrelated `TryHit`
dispatch. It also exposed an observer projection omission for side-condition
layers. None was repaired as a move-pair branch.

Minimization preserves a divergence signature: first boundary, JSON path, and
mismatch class. The implemented reducer keeps the causal prefix through that
boundary and removes only the irrelevant suffix. Interior deletion would alter
the generated trajectory and is not treated as an honest reduction. It runs
fresh oracle/native replays twice, rejects fingerprint drift or nondeterminism,
and atomically retains an executable case, copied teams, choice counts, output
digests, and the pinned failure identity.

## Serialized integration gate

`verify/checkpoint7.sh` is the single serialized gate. It requires separate
clean and observer-patched checkouts of the pinned revision, runs the exact
regression maps, native/unit/sanitizer/10,000-battle robustness suites, curated
and 1,250-case admission differentials, deterministic full-battle campaign,
complete boundary corpus, and the calibrated Ocean performance gate. It writes
only verifier evidence below `POKEMON_CHECKPOINT7_EVIDENCE_DIR`; it does not
regenerate canonical source or classification files.

Agents may audit or prepare independent assertion families and randomized
seeds. Changes to the canonical maps, kernel/API, generated data, observer,
case compilation, and full verification gates remain serialized in the
integration worktree.

## Current gate evidence

The current kernel and generated bundle pass the complete checked differential
corpus at 3,225 boundaries across 722 cases, including a second byte-stable
replay. The original legal random full-battle campaign matches 405 boundaries
across four natural terminal battles twice. A deterministic team-recombination
campaign independently matches 280 boundaries across four natural terminal 6v6 battles twice. Its
reducer is fingerprint-preserving and retains only a causal prefix; it does not
delete interior choices and pretend the resulting trajectory is equivalent.

The admission verifier matches all 136 curated cases. Its bounded randomized
extension matches 1,250 deterministic source recombinations: 625
oracle-accepted teams that the deliberately incomplete native validator labels
`INCOMPLETE`, and 625 source-invalid teams rejected for `obtainablemoves`.
This is evidence for the declared admission subset, not full Team Validator
parity. Species Clause, the Gen 3 Smeargle/Ingrain rule, the three Baton Pass
plus trapping-move rules, Speed Pass, One Boost Passer, EV Limit, OHKO Clause,
and Accuracy Trap Clause are closed by generated admission rules and focused
differential evidence. A native `LEGAL` result and the remaining unsupported
Team Validator surface remain open.

ASan/UBSan pass the focused kernel, 128-battle random legal-play, Ocean adapter,
admission, and PRNG suites. A separate 10,000-battle run reaches its 128-decision
cap without invariant failure. The current Ocean calibration uses 1,024
environments and preserves a stable digest, but it still measures the legacy
production ABI with a switch-heavy workload. Its observed throughput and RSS
are calibration data only; a Harbor performance floor must not be frozen until
the complete mechanics path is the measured path.
