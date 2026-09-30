# Pokemon Gen 3 OU — Ocean env (dev)

C battle engine for Gen 3 OU singles, being adapted to the PufferLib Ocean
contract.

The approved bounded Harbor implementation-and-verification contract lives at
[`harbor/gen3ou-native/README.md`](harbor/gen3ou-native/README.md). It defines
the observable contract, supported-feature map, scoring gates, and honest
definition of completion used to govern the interpreter migration.

[`CONFORMANCE_CHECKPOINTS.md`](CONFORMANCE_CHECKPOINTS.md) defines the ordered
implementation checkpoints and maps them to pinned Showdown test sources.

## Status

`native/` contains the replacement battle runtime. It owns the first complete
generic slice: choices, requests, action ordering, ordinary hits, switching,
fainting, forced replacement, terminal resolution, and deterministic replay.
The frozen Checkpoint 5 corpus agrees with pinned Showdown at 198 stable
boundaries across 68 cases. It additionally covers bounded condition
lifecycle, generic boosts/secondaries, recoil/drain, multi-hit execution, and
fixed/HP-bracket damage. This is a supported-feature conformance result, not a
claim of complete Gen 3 OU inventory coverage.

`engine/gen3_abi.c` and `engine/gen3_abi.h` contain the earlier resolver-based
engine. Keep that engine as regression evidence. Do not add move-pair branches
or inferred PRNG frame counts to it.

`ocean/pokemon_slice.h` is the thin Ocean adapter for the replacement runtime.
It uses fixed buffers and contains no battle mechanics. Full 6v6 Gen 3 OU
coverage, the ordered native handler system, production PufferLib integration,
and the rollout wrapper remain unfinished.

`engine/data_gen3.h` and `data/gen3_ids.json` are generated from the pinned
oracle by `tools/generate_gen3_data.js`. They contain all 392 distinct Gen 3
species/form identities, 354 moves, 76 abilities, canonicalized item IDs, and
the 17-type effectiveness table. The header also begins the interpreter's
reviewed effect-descriptor table with Spikes, Leftovers, Natural Cure,
Levitate, Sturdy, and Torrent; generation rejects callback-inheritance drift.
Moves now also carry resolved targets, immunity/critical metadata, and compact
primary/secondary programs for ordinary status and boost effects. Unsupported
executable effects are marked `NATIVE_REQUIRED` rather than silently omitted.
Base species retain their National Dex number;
alternate formes receive stable IDs above 386 so the ABI does not collapse
distinct states such as Deoxys-Attack and Deoxys-Defense.

`engine/gen3_move_hit.c/.h` is the compiled but not-yet-routed arithmetic seam
for ordinary hits. It has typed hit outcomes and named PRNG stages.
`engine/gen3_move_program.c/.h` executes generated status/boost programs with
Showdown's secondary-chance staging and independent per-effect acceptance.
Callers must still normalize mutable battle modifiers and own action, event,
faint, residual, and request execution. These unit tests are not an end-to-end
battle claim.

Verifier builds may define `GEN3_VERIFY_TRACE` and install the synchronous sink
in `engine/gen3_verify_trace.h`. It streams typed checkpoints, phases, requests,
protocol events, terminal resolution, and exact scheduler tie PRNG draws without
a native trace buffer. Queue/handler detail and remaining semantic PRNG labels
advance with the interpreter migration; guessed legacy frame consumption is
deliberately not mislabeled as proof.

## Source

Vendored from smogon-vgc-rl commit
`aa94c98b297a3d6c3ea049aa22082427265040e9`.

The executable correctness oracle is Pokémon Showdown at commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`. The harness feeds identical teams,
seeds, and choices to the native engine and Showdown, then compares snapshots,
legal choices, protocol-visible behavior, and PRNG state at each supported
decision boundary. See `ORACLE.md` for setup and the exact correctness claim.

## What needs doing

1. Replace the legacy resolver dispatcher incrementally with the explicit
   action scheduler, event interpreter, generic move pipeline, and generated
   effect descriptors in `ARCHITECTURE.md`, preserving differential evidence at
   every migration seam.
2. Expand the checked regression corpus across battle identities and mechanics.
3. Write `collect_pokemon.py` that produces `list[Step]` for the robots training
   loop.
4. Carry the native terminal result into the production Ocean reward/reset
   lifecycle after complete-battle inventory coverage exists.

The next native checkpoint is the Gen 3 OU inventory: classify every reachable
species, move, ability, item, condition, target mode, and event hook from the
pinned revision, then attach source-linked focused and recombined evidence.

## Ocean env contract

PufferLib 5.x uses `pufferenv.h`, an `Agent agents[2]` array with per-agent
observation/action/reward buffers, and `puf_init`, `puf_reset`, `puf_step`,
`puf_render`, `puf_close`, and `puf_log`. See `PUFFERLIB.md`. The adapter models
`num_agents=2`, loads an exact normalized `Gen3BattleInit`, publishes symmetric
perfect-information observations and masks, and owns reset. Terminal reset
remains deliberately absent until native complete-battle semantics exist.

## Native verification

The project-local verification skill at
`.cursor/skills/verify-pokemon-gen3/SKILL.md` is the maintained entry point for
doctor checks, feature coverage, structural Showdown tracing, causal-prefix
minimization, and coverage-guided scenario expansion.

```sh
make -C engine clean all test
node tools/generate_gen3_data.js /path/to/pokemon-showdown header \
  | cmp engine/data_gen3.h -
node tools/generate_gen3_data.js /path/to/pokemon-showdown ids \
  | cmp data/gen3_ids.json -
POKEMON_SHOWDOWN_DIR=/path/to/pokemon-showdown \
  python -m unittest discover -s tests -v
POKEMON_SHOWDOWN_DIR=/path/to/pokemon-showdown \
  python harness/diff.py --battles 1 -j 1 --seed 42
POKEMON_SHOWDOWN_DIR=/path/to/pokemon-showdown \
  python harness/diff.py --corpus regressions/gen3ou -j 1
```

The native target currently runs eight strict C suites, including focused move
hit/program/preflight tests and the observation-only verifier trace contract.

Protect now has explicit consecutive-use state and typed activation/block
events. Toxic models status application, staged residual damage, and Natural
Cure on switch-out. ABI v12 also models Leech Seed as a switch-cleared
volatile, including typed start events and drain/heal residuals, plus the five
battle stat stages and typed boost/unboost events. Forced-switch snapshots also
distinguish an interrupted turn with residual work from an end-of-turn KO, and
the snapshot exposes terminal state and the winning side.

The checked regression corpus records named, finite choice prefixes that have
been revalidated against both the current engine and the pinned oracle. A
separate generated run continues past its recorded prefix to discover the next
unsupported boundary. Passing either finite surface is evidence for those
specific traces; it does not yet mean complete Gen 3 OU.
The harness queries Showdown's live PRNG after every nonterminal decision boundary and
compares it with the native snapshot. The query uses Showdown's debug evaluator
but neither advances the PRNG nor changes battle state; its response is consumed
out-of-band and never treated as battle protocol. Showdown stops servicing
debug queries after its terminal block, where the harness instead verifies the
complete protocol, winner, terminal flag, and empty legal-action sets.

Protocol comparison is semantic rather than textual. The ABI exposes typed
events, and the harness projects Showdown's protocol onto the same tuples. This
removes presentation-only timestamps, nicknames, and duplicate percentage HP
lines while retaining event kind, order, side, species identity, and exact HP.
Initial placement and the supported turn slices emit and verify typed switch,
move, damage, heal, and failure events. Each additional mechanic must extend this event
sum type before it can be declared supported.
