# Pursuit queued-action interception

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Pursuit is evidence for a generic `BeforeSwitchOut` interception boundary. It
must not become a named-move resolver.

## Pinned Showdown control flow

1. Queue construction expands the selected move into an order-5 pre-turn
   action and its ordinary move action.
2. Gen 3's pre-turn override rejects registration when the user begins the
   turn asleep or frozen, then installs a one-turn target volatile retaining
   the move user as source.
3. A voluntary switch marks the outgoing target as being recalled and
   dispatches `BeforeSwitchOut` before `SwitchOut`, owner `End`, cleanup, and
   entry lifecycle.
4. The target condition cancels the registered source's queued move and
   explicitly deducts PP and records the selected move, then enters
   `useMove`. This reuses targeting, hit, damage, faint, `AfterMove`, and PRNG
   staging, but deliberately does not dispatch a second `BeforeMove` gate.
   Consequently paralysis does not prevent the Gen 3 interception.
5. Recall context makes accuracy unconditional and doubles base power from 40
   to 80. Thus interception consumes no accuracy draw but retains ordinary
   critical and damage-roll draws.
6. If interception faints the outgoing target, generations 2--4 continue the
   already selected switch. This is a typed generation policy, not a Pursuit
   branch.

Authoritative sources are `data/moves.ts#pursuit`,
`data/mods/gen3/moves.ts#pursuit`,
`data/mods/gen4/moves.ts#pursuit`, `sim/battle-actions.ts#switchIn`, and
`sim/battle.ts#runAction`. The direct upstream singles regression is
`test/sim/moves/pursuit.js`, `[Gen 3] should continue the switch`.

## Native boundary

The smallest reusable implementation consists of:

- generated pre-turn installation target (`USER` or `MOVE_TARGET`) and a
  generated status-admission mask;
- a generic ordered `BeforeSwitchOut` event;
- source provenance in the installed target volatile;
- a bounded operation which removes the matching source move action, performs
  its selected-action PP/history bookkeeping exactly once, and invokes it at
  the post-`BeforeMove` `useMove` boundary;
- explicit recall context consumed by generated accuracy and base-power
  policies; and
- a generation policy controlling continuation of a preselected switch after
  an interception faint.

All capacity and bundle compatibility checks must reject before mutation or
PRNG consumption. Public battle boundaries must never retain transient recall
state.

## Required evidence

- ordinary non-switching Pursuit: 40 power and ordinary accuracy staging;
- surviving interception: 80 power, always hit, no accuracy draw, queued move
  consumed once, then the selected switch completes;
- interception knockout: faint resolves before the Gen 3 preselected switch;
- sleep and freeze at turn start prevent registration;
- paralysis does not add a second action-gate draw and does not prevent the
  interception;
- the condition expires without repeating next turn; and
- Pressure and choice-lock recombination preserve PP and handler ordering.

Only these four inventory records close after focused, differential, replay,
and full-corpus proof: `move:pursuit`, `condition:volatiles.pursuit`,
`event_hook:move.pursuit.onModifyMove`, and
`event_hook:move.pursuit.condition.onBeforeSwitchOut`.

## Achieved evidence

The generic boundary is implemented and all five legal Pursuit fixtures match
the pinned oracle. The complete corpus matches at 2,219 semantic boundaries
with deterministic replay. Focused native, randomized-play, Ocean adapter,
ASan/UBSan, and generated-data reproducibility gates pass. The feature map
therefore promotes exactly the four records above; it makes no broader
switching or state-transfer claim.
