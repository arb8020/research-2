# Gen 3 battle interpreter architecture

This document defines the replacement architecture for `engine/gen3_abi.c`.
It is based on the pinned Pokemon Showdown source at commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, not on the existing seeded
divergence cases.

The public shape stays unchanged:

- `engine/gen3_abi.h` is the stable native ABI.
- `engine/gen3_abi.c` owns all battle mechanics and runtime state.
- `ocean/pokemon_gen3.h` is a thin PufferLib Ocean adapter.
- generated headers contain normalized Gen 3 data; Showdown and Python are
  build/test-time dependencies only.

The current pair-specific `resolve_X_and_Y` implementation is migration input,
not the target design. Hand-counted PRNG frames are not a valid abstraction:
Showdown consumes randomness while ordering actions and event handlers even
when no visible state or protocol event changes.

## Inspected Showdown boundaries

### Canonical state

The aggregate root is `Battle` in `sim/battle.ts`. It owns sides, field state,
the PRNG, the action queue, the faint queue, request state, turn phase,
terminal state, and the currently executing event/effect context.

`Side` in `sim/side.ts` owns team order, active positions, side and slot
conditions, the current request, and the pending choice accumulator.

`Pokemon` in `sim/pokemon.ts` owns persistent and battle-local combatant state:
HP, PP, status and status state, volatiles, boosts, ability and item state,
switch/faint flags, and per-turn move bookkeeping. `Field` owns weather and
pseudo-weather. Showdown's open-ended `EffectState` cannot be copied literally
into a fixed C environment; the C model needs tagged, bounded payloads for the
Gen 3 effects it supports.

### Choice and action algebraic data types

External choices enter through `Battle.choose` -> `Side.choose`. Parsing and
validation produce the side-local `ChosenAction` sum type (`move`, `switch`,
`pass`, and preview-only variants). `Side.commitChoices` submits those choices
to `BattleQueue.resolveAction` in `sim/battle-queue.ts`.

`resolveAction` is the normalization boundary. It produces a fully populated
queued `Action` sum type:

- move;
- switch / instant switch;
- run-switch;
- before-turn;
- residual;
- event;
- start/pass (and irrelevant later-generation variants).

An action carries its order, priority, speed, actor, target, and effect ID.
Queue order is `(order ascending, priority descending, speed descending,
sub-order ascending, effect-order ascending)`, with exact ties shuffled by the
PRNG. `fractionalPriority` is resolved before comparison and folded into an
action's priority by `Battle.getActionSpeed`; it is not an additional
comparator key.

### Queue and suspension semantics

`Battle.commitChoices` constructs and sorts newly submitted actions. During a
mid-turn forced replacement it preserves the untouched continuation queue,
sorts only the new replacement actions, and appends the saved continuation.
The old queue is not reconstructed or re-sorted.

`Battle.turnLoop` adds `beforeTurn` and `residual`, then executes one action at
a time through `Battle.runAction`. An action may:

1. mutate state and emit protocol;
2. enqueue `runSwitch` or another action;
3. enqueue faints;
4. suspend at a forced-switch request with the remaining queue intact;
5. terminate the battle.

For Gen 3, fainted replacements are checked after every move and residual
action. A hazard KO can therefore suspend and resume the same turn more than
once.

### Event dispatch

The effective mechanics interpreter is `singleEvent`, `runEvent`, `eachEvent`,
and `fieldEvent` in `sim/battle.ts`.

- `singleEvent` invokes one effect handler with its attached state.
- `runEvent` discovers handlers from the target, source, allies/foes, side,
  field, format, item, ability, status, and volatiles; orders them; threads a
  relay value; and short-circuits on failure.
- `eachEvent` orders active Pokemon by speed and dispatches one event to each.
- `fieldEvent` materializes and sorts residual/switch-in handlers, validates
  that each effect is still attached before invocation, decrements durations
  in order, and drains the faint queue after each handler.

Handler ordering is observable through PRNG state. It must be represented
even when every handler is a no-op for visible state.

Gen 3 is composed from the generic simulator, inherited Gen 4 behavior, and
the overlays in `data/mods/gen3/`. Important sources are:

- `data/mods/gen3/scripts.ts`: Gen 3 move-hit and damage pipeline;
- inherited `data/mods/gen4/scripts.ts`: `runSwitch` staging;
- `data/mods/gen3/{moves,abilities,items,conditions}.ts`: effect handlers;
- base `data/{moves,abilities,items,conditions}.ts`: inherited definitions.

### Turn phases, requests, and terminal resolution

The runtime phases are:

1. `INIT`: start actions and initial switch-ins;
2. `AWAIT_MOVE`: expose a move request and accept one choice per live side;
3. `RUN_QUEUE`: execute normalized actions;
4. `AWAIT_SWITCH`: suspend with an untouched continuation queue and request
   replacements only from affected sides;
5. `RESIDUAL`: execute the globally ordered residual handler list;
6. `TERMINAL`: winner/tie fixed, request state cleared, no legal actions.

`makeRequest`/`getRequests` in `sim/battle.ts` derive move, forced-switch, and
wait requests from canonical state. Requests are not canonical battle state
themselves. `faintMessages` drains the faint queue and calls `checkWin` before
a replacement request is issued. `win`/`tie` emit terminal protocol, set the
winner and ended flag, and clear all requests.

### PRNG

All randomness flows through `sim/prng.ts`. Numeric four-word seeds use the
64-bit `Gen5RNG` stream that the current ABI already reproduces. One draw is
consumed by every call to `random`; `randomChance`, `sample`, and Fisher-Yates
`shuffle` are derived operations.

The important distinction is between:

- mechanic draws: accuracy, critical hit, damage roll, secondary effect,
  random target, random phaze target;
- structural draws: tied action insertion/sorting, tied event-handler sorting,
  residual ordering, and the Gen 3 end-turn Quick Claw roll.

There must be one PRNG API in the C engine. No resolver may advance it by an
inferred number of frames.

## Target C architecture

All collections are fixed-capacity arrays so a battle is self-contained,
copyable, and vectorization-friendly. Capacity exhaustion is an invariant
failure, not a silent fallback.

### 1. Battle state

`Gen3Battle` remains opaque publicly and owns:

- two `Gen3SideState` values;
- twelve `Gen3PokemonState` values plus immutable normalized sets;
- field and side conditions;
- a fixed action queue and faint queue;
- the current request/phase and suspended-turn flag;
- PRNG seed;
- a bounded typed protocol-event buffer;
- terminal result and turn counters;
- current event context and per-turn scratch state.

Pokemon, side, field, status, volatile, item, and ability effects use tagged
effect slots. Each tag selects a generated effect descriptor; effect-specific
mutable values use a small tagged payload union. Illegal combinations are
rejected when teams/state are normalized.

### 2. Closed choice and action ADTs

Use separate types for user intent and scheduled work:

```c
typedef enum { GEN3_CHOICE_MOVE, GEN3_CHOICE_SWITCH, GEN3_CHOICE_PASS }
    Gen3ChoiceKind;

typedef enum {
    GEN3_ACTION_MOVE,
    GEN3_ACTION_SWITCH,
    GEN3_ACTION_RUN_SWITCH,
    GEN3_ACTION_BEFORE_TURN,
    GEN3_ACTION_RESIDUAL,
    GEN3_ACTION_EVENT
} Gen3ActionKind;
```

Choice validation derives legal actions from the current request. Choice
commit normalizes targets, priority, and speed into actions. Execution never
reinterprets raw action integers. A forced-replacement action remains owned by
the fainted active Pokemon, so its ordering speed is the outgoing active's,
not the incoming replacement's.

### 3. Explicit scheduler

The scheduler owns queue construction, comparison, tie shuffling, insertion,
and suspension. Its transition is one action at a time:

```text
choice commit -> normalized actions -> sorted queue
                                      |
                                      v
request <- suspend <- execute action -> post-action pipeline -> next action
                                                        |
                                                        v
                                              residual -> end turn
```

The post-action pipeline is fixed and visible: phazing, clear active move,
drain faints/check terminal, discover forced replacements, Gen 3 `Update`,
then continue. A forced request retains the exact remaining queue.

### 4. Event interpreter

Represent a scheduled handler explicitly:

```c
typedef struct {
    Gen3EventId event;
    Gen3EffectRef effect;
    Gen3EffectHolder holder;
    Gen3HandlerId handler;
    int16_t order;
    int16_t priority;
    int16_t sub_order;
    uint16_t speed;
    uint16_t effect_order;
} Gen3Handler;
```

Handler discovery is generic and driven by effect descriptors. Sorting uses
the same comparator/tie shuffle as the corresponding Showdown event family.
Dispatch threads a typed relay value (`bool`, integer damage, move/type ID, or
boost table) and exposes explicit `FAIL` versus `SILENT_FAIL` results.

This is not a general JavaScript VM. Most handlers should use a compact set of
generated declarative operations, for example:

- apply fixed/fractional damage or healing;
- apply/cure status or volatile;
- modify priority, accuracy, power, stat, type, or damage;
- add/remove side condition;
- force switch or self-faint;
- emit a typed protocol event.

Mechanics that cannot be represented honestly by those operations use a
small, named native `Gen3HandlerId`. The handler is selected by generated
data, not by a move-pair branch.

### 5. Generated data

Extend `tools/generate_gen3_data.js` and `engine/data_gen3.h` from scalar move
metadata to normalized effect descriptors:

- move target/category/priority/accuracy/PP/flags;
- primary and secondary effect programs;
- item, ability, status, volatile, weather, and side-condition handlers;
- handler event, order, priority, sub-order, and native/declarative opcode;
- Gen 3 override already resolved through Showdown's mod inheritance chain.

The generated representation is checked in and reproducible from the pinned
oracle. The runtime never loads JSON, JavaScript, Python, or Showdown.

### 6. Mutation and protocol primitives

Only mutation primitives change HP, PP, status, boosts, active position,
effects, or faint state. They also emit the corresponding typed ABI event.
This keeps protocol order coupled to the state transition that caused it while
allowing presentation-only Showdown lines to remain outside the ABI.

Damage is one generic pipeline: target/immunity, accuracy, TryHit handlers,
critical hit, base damage, modifier phases, type effectiveness, randomizer,
damage application, secondary effects, and post-hit events. Status moves use
the same event pipeline and failure algebra; they are not separate pairwise
resolvers.

### 7. Requests and legal actions

The phase/request sum type is canonical. Legal-action masks and request
snapshots are pure projections from it plus side/Pokemon state. Forced switch
requests can address one or both sides, and a waiting side has no action.

The Ocean adapter continues to do only three things: project observations,
copy legal masks, and submit validated action IDs to the ABI.

## Migration and proof plan

The rewrite proceeds by semantic layer, not by move pair:

1. Freeze the current differential artifacts as a replay corpus. Preserve the
   existing engine and adapter tests; stop adding resolver branches.
2. Introduce the phase, choice, action, queue, faint-queue, and request types
   inside `gen3_abi.c`. Route switches and inert turns through the scheduler.
3. Add generic event discovery/sorting with explicit PRNG calls. First prove
   the existing switch-only traces, including the currently observed invisible
   `Update`, `Residual`, and Quick Claw draws.
4. Generate effect descriptors and implement switch-in, hazards, items,
   abilities, statuses, and residuals through the event interpreter.
5. Implement the generic move pipeline and migrate moves by effect class:
   damage, status, healing/protection, side conditions, phazing, self-KO, then
   exceptional native handlers.
6. Delete a legacy resolver only when every corpus transition that reached it
   passes through the interpreter. Do not keep a runtime fallback that silently
   changes semantics; an unmigrated transition fails explicitly.
7. Expand differential testing from seeded trajectories to focused transition
   generation and complete random battles. Compare canonical state, legal
   actions, typed protocol events, terminal result, and exact PRNG seed at
   every decision boundary.
8. Run the production PufferLib compile/integration gate and vectorized reset /
   step tests only after the interpreter completes full battles.

Completion means the interpreter can run complete legal Gen 3 OU singles
battles without an unsupported transition, and the differential corpus plus
broader generated battles agree with the pinned oracle at every boundary.

### Current move-pipeline strangler boundary

`engine/gen3_move_hit.c/.h` now implements and tests the restricted arithmetic
kernel for an ordinary hit: natural immunity discovered from the type chart and
current generated ability capabilities, optional accuracy, a distinct ordered
post-accuracy `TryHit` boundary, critical hit, damage roll, and an explicit
`IMMUNE | MISSED | FAILED | CONNECTED` result. Each random call is named by the
semantic operation that owns it. Combatants carry current battle stat stages,
including Gen 3 critical-stage bypass rules, and the context exposes the exact
pre-`+2` burn, Phase-1, and weather rounding seams. Callers still own
accuracy/evasion, handler discovery, and composition of each named modifier.
The kernel is compiled into the native library but is not yet called by the
legacy turn dispatcher.

`engine/gen3_move_program.c/.h` is the matching compact executor for generated
ordinary status and boost effects. It preflights only structural validity and
runtime opcode capability. For secondaries it then consumes the labeled chance
draw before consulting target state, as Showdown's
`BattleActions.secondaries` does. Operations apply independently in descriptor
order, so a two-boost primary can raise one uncapped stat even when the other
is already capped. Target immunity, an existing status, and a capped boost are
semantic no-effect results from the mutation boundary; they are not confused
with an unsupported opcode. This executor is also compiled and unit-tested but
not yet routed by the legacy dispatcher.

`engine/gen3_move_preflight.c/.h` is the mutation-free admission boundary in
front of both kernels. Generated move data records whether resolved Showdown
semantics require native execution (callbacks, multihit, variable/fixed
damage, recoil/drain, switching, field effects, and similar exceptions).
Preflight additionally requires a singles-compatible target, supported
program opcodes, explicitly known handler-free attached effects, neutral
accuracy/evasion stages, and no undiscovered modifier hooks. Rejection occurs
before PP, protocol, battle state, or PRNG mutation; tests compare a real ABI
battle snapshot and seed byte-for-byte. It remains deliberately unrouted until
the action interpreter owns the complete surrounding transition.

That separation is intentional and temporary. The next migration unit is an
action interpreter for ordinary single-target damaging moves that owns PP,
typed events, application, secondary effects, faint draining, residuals, and
request transitions around this hit core. Once all matching corpus transitions
use that path, the corresponding pair resolvers and their inferred frame counts
must be deleted together. Until then, the seed-42 battle-6 immunity frontier is
diagnostic evidence, not a passing regression claim.
