# Gen 3 switch lifecycle and Start/End plan

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Showdown boundary

Gen 3 inherits the Gen 4 `actions.runSwitch` implementation
(`data/mods/gen4/scripts.ts:15-52`). Its lifecycle is:

```text
switchIn: BeforeSwitchOut -> SwitchOut
          -> ability End -> item End -> clear outgoing volatile state
          -> install incoming + fresh ability/item state
          -> BeforeSwitchIn -> enqueue runSwitch

runSwitch: EntryHazard -> SwitchIn
           -> if still alive: mark started -> ability Start -> item Start

faint: BeforeFaint -> Faint -> ability End -> item End
       -> clear volatile state -> mark inactive/fainted -> replacement request
```

The authoritative control-flow locations are
`sim/battle-actions.ts:62-159`, `data/mods/gen4/scripts.ts:15-52`,
`sim/battle.ts:3212-3260`, and `sim/battle.ts:3447-3601`. Initial leads also
enter through `switchIn`/queued `runSwitch` (`sim/battle.ts:3360-3390`); Start
must not be a separate initialization shortcut.

Start and End here are **single-owner lifecycle events**, not ordinary global
discovery. `singleEvent` invokes the selected installed effect and state
directly. Conditions use the same primitive at their natural ownership
boundary: Start on successful installation (with rollback when Start rejects),
End before removal (`sim/pokemon.ts:1740-1752`, `1900-1962`, `2028-2072` and
`sim/side.ts:470-500`). Global `SwitchIn` discovery is separate.

Ordering is explicit rather than priority-sorted: on Gen 3 entry, ability
Start precedes item Start; on ordinary switch-out and faint, ability End
precedes item End. Entry hazards and SwitchIn handlers precede both Starts. A
Pokémon killed before the Start boundary receives neither Start.

`singleEvent` also supplies the important applicability rules
(`sim/battle.ts:1190-1235`):

- a stale status owner is skipped;
- ability Start is skipped while the ability is ignored, but ability End is
  deliberately allowed so cleanup cannot be stranded;
- item Start is allowed while the item is ignored; other item events,
  including End, are skipped while ignored;
- fainted holders are skipped by field-event iteration, while the explicit
  faint path still calls ability/item End before teardown;
- weather suppression skips ordinary weather callbacks, but not FieldStart,
  FieldResidual, or FieldEnd.

For effective Gen 3 Cloud Nine, the Gen 4 override makes Start only clear its
`ending` marker (`data/mods/gen4/abilities.ts:37-43`); inherited End sets the
marker and emits WeatherChange (`data/abilities.ts:533-550`). The suppression
predicate requires an active, living, non-ignored holder whose ability does
not have `ending` set (`sim/field.ts:109-118`). Sand Stream Start performs the
ordinary field weather transaction (`data/abilities.ts:3956-3963`).

## Native gap

`execute_switch` currently performs outgoing reset, changes `side->active`,
refreshes ability/item generations, and emits the public switch event in one
function. It dispatches neither outgoing End nor incoming Start. Initial leads
also emit switch observations without traversing a shared entry lifecycle.
Faint resolution marks the holder fainted and requests replacement without
the same End boundary. Cloud Nine suppression is currently inferred by
scanning live ability descriptor data, so stored weather becomes suppressed,
but there is no evidence for the actual Start/End lifecycle. Sand Stream has
no generic way to set weather from Start.

## Smallest honest implementation slice

Add one compact lifecycle interpreter, not Cloud Nine or Sand Stream branches:

1. Add `Start` and `End` to the executable event algebra with a no-relay
   lifecycle context and declarative opcodes sufficient for:
   `SET_OWNER_FLAG(ending, bool)`, `SET_WEATHER(kind, duration-policy)`, and
   `EMIT_EVENT(WeatherChange)`. The weather opcode must call the existing
   generic weather transaction; it must not write field state itself.
2. Add a direct `dispatch_owner_lifecycle(event, owner_ref)` boundary. It
   resolves exactly the currently installed ability, item, status, or
   condition owner, verifies the owner generation/state token, applies the
   event-specific ignored/fainted rules above, and executes one descriptor.
   Do not use broad target/source/foe/any discovery for this operation.
3. Split switching into visible stages: outgoing End (ability then item),
   teardown/install, existing SwitchIn observation/handlers, liveness check,
   incoming Start (ability then item). Route initial leads, voluntary switches,
   and forced replacements through the same incoming stages.
4. Route faint teardown through the same outgoing End pair before volatile
   clearing and before exposing the replacement request. End-generated work
   must drain before request/terminal resolution continues.
5. Represent Cloud Nine's `ending` as explicit mutable ability-state payload.
   Effective-weather lookup remains generic descriptor-driven and checks
   active + living + non-ignored + not-ending. Start/End merely maintain that
   invariant and emit generic WeatherChange.
6. Generate Sand Stream Start as `SET_WEATHER(SANDSTORM, indefinite)`. Reusing
   the weather transaction gives replacement, FieldEnd/FieldStart, trace, and
   residual behavior without an ability-name branch.

Do not add a general callback VM, dynamic lifecycle registry, or a
`resolve_cloudnine`/`resolve_sandstream` function. The fixed opcode products
above are the complete semantic surface needed for this slice.

## Inventory closure

This slice closes exactly **5 descriptor-map obligations**:

- Cloud Nine: ability descriptor plus `ability.cloudnine.onStart` and
  `ability.cloudnine.onEnd` = 3;
- Sand Stream: ability descriptor plus `ability.sandstream.onStart` = 2.

The generic Start/End event implementation is structural evidence, not a claim
that every reachable Start/End hook is supported. All other hooks stay
unsupported until their programs and interaction cases are proven. Sand Stream
cannot be credited unless indefinite Sandstorm already has complete weather
transaction/residual evidence; otherwise retain all 2 obligations as
unsupported.

## Required evidence

Focused native tests:

- initial lead and replacement use the same incoming lifecycle;
- voluntary switch and faint dispatch ability End then item End before
  teardown/request; a pre-Start faint dispatches no Start;
- stale owner generation rejects/skips safely; ignored ability suppresses
  Start but not End; inactive/fainted Cloud Nine never suppresses weather;
- Cloud Nine entering/leaving/fainting toggles only effective weather, never
  deletes stored weather, and emits WeatherChange after each transition;
- Sand Stream from clear, finite Sandstorm, and indefinite Sandstorm uses the
  generic transaction and leaves an indefinite condition;
- Start/End program or trace capacity failure is atomic.

Differential cases must preserve choices plus resulting state and compare the
first boundary across queue/action, owner handler order, field condition,
effective weather, phase/request, terminal result, and labeled PRNG:

1. initial Cloud Nine versus stored weather and ordinary initial lead;
2. Cloud Nine voluntary entry and exit;
3. Cloud Nine faint followed by forced replacement;
4. Sand Stream initial lead, voluntary entry, and forced replacement;
5. Sand Stream replacing finite Sandstorm and re-entering indefinite
   Sandstorm;
6. a recombination battle where Cloud Nine suppresses Sand Stream weather,
   then exits or faints and the still-stored Sandstorm becomes effective.

The observer patch must expose lifecycle event identity, owner kind/id,
holder, invoked/skipped reason, sequence, ability `ending`, stored versus
effective weather, and the request transition. Any tie/order PRNG observed in
Showdown's queued initial/replacement entry path must receive a stable label and
match exactly; do not consume a guessed draw in native code.

## Implementation evidence (2026-09-22)

The bounded interpreter now has generated Cloud Nine Start/End and Sand Stream
Start programs using the shared stale-checked owner lifecycle dispatcher.
`weather-cloud-nine-switch.json` proves Cloud Nine voluntary entry and exit
against the pinned oracle. `weather-sand-stream-start.json` is intentionally a
zero-choice, one-boundary artifact: it proves initial Sand Stream Start,
permanent Sandstorm state, handler metadata, and deterministic initialization
without advancing into unrelated residual semantics.

The wider matrix above is not closed. Forced-replacement and faint-driven
Start/End use the shared native dispatch path but lack differential artifacts,
so they receive no inventory credit. A diagnostic turn after permanent
Sandstorm showed equal HP/state/events but a verifier disagreement: Showdown
emits residual discover, two weather-damage, and residual execute condition
records while the native observer emits only discover. Permanent-weather
residual structural tracing therefore remains unsupported work; it is not
hidden by an immunity-only fixture and is not evidence for these obligations.
