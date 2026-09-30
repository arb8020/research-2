# Turn-local retaliation provenance

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Counter and Mirror Coat are the first witnesses for one reusable capability:
turn-local capture of an ordered damage relay, followed by state-derived fixed
damage. They are not separate move resolvers.

## Showdown boundary

- `sim/battle-queue.ts` expands `beforeTurnCallback` into an order-5
  `beforeTurnMove` action.
- `data/moves.ts` installs a duration-one, `noCopy` condition and rejects the
  response when no damage was captured.
- `data/mods/gen3/moves.ts` observes the `Damage` relay at priority `-101`.
  Counter accepts Physical damage plus Hidden Power; Mirror Coat accepts
  Special damage except Hidden Power. The condition stores twice the requested
  damage before current-HP capping.
- `sim/battle-actions.ts` resolves the stored value as fixed damage, so the
  response still owns type immunity and numeric accuracy but owns no critical
  or damage-roll draw.
- `sim/pokemon.ts#getMoveTargets` dispatches `RedirectTarget` only when
  `activePerHalf > 1`. Those two redirect hooks are unreachable in the current
  Gen 3 OU singles format; `scripted` otherwise resolves to the sole foe.

## Native boundary

The generic queue can expand a selected move into a preparation action and its
ordinary move action. Generated move data selects a preparation descriptor and
a generation-flattened retaliation class. The event interpreter owns four
small operations: initialize the condition payload, guard a `Damage` event by
class and opposing source, capture twice the current relay, and require a valid
capture. A state-derived damage formula reads the descriptor-selected payload.

The mutable payload is:

```text
captured: bool
source_side: side
source_position: active position
damage: u32
```

`source_position` is retained for the semantic capability, but the current
format has one fixed active position per side. No doubles redirection claim is
made. Hidden Power's Gen 3 provenance exception is generated declaratively;
its per-Pokemon type, category, and power are now constructed through the
generation-owned personal-move profile boundary. Promotion remains contingent
on the complete differential and replay gates rather than this implementation
fact alone.

## Evidence gate

Focused native evidence currently proves:

- preparation is a distinct order-5 action and four-action tie groups consume
  exactly their owned queue draws;
- Physical fixed damage feeds Counter and Special fixed damage feeds Mirror
  Coat;
- the response deals exactly twice the captured damage;
- the wrong response class produces no capture;
- numeric 100 accuracy is still drawn, while fixed responses consume no
  critical or damage-roll draw;
- the duration-one condition expires through the generic lifecycle;
- malformed preparation descriptors fail before mutation.

Fifteen legal differential fixtures additionally prove miss/no-history failure,
incoming and response type immunity with Gen 3 accuracy staging, Substitute
interception before `Damage`, last-hit overwrite across a fixed two-hit move,
pre-resolution self-faint followed by forced replacement without executing the
queued response, resolved Weather Ball category, delayed Future Sight
provenance, and natural overkill followed by forced replacement. A focused C
test invokes the internal ordinary-move `Damage` relay with a one-HP holder and
proves the condition captures twice the requested value before HP capping.
The complete corpus and deterministic replay remain the promotion gate.

The aggregate moves, volatile descriptors, two `onStart`, two `onTry`, and two
reachable `onDamage` records are implemented. The two
`onRedirectTarget` records are unreachable under the singles topology proof
above; they are not implemented handlers. The `scripted` target mode is
implemented for the singles topology and source-provenance failure rules; no
doubles redirection claim is made.
