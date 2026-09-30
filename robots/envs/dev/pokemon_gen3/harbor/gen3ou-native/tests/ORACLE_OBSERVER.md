# Verifier-only Showdown observer

`oracle-observer.patch` applies only to the pinned Showdown tree baked into the
separate verifier image. It is never copied into the submitted native runtime.

The patch adds typed observation records including:

- `prng`: every low-level `PRNG.random` draw, including draws owned by shuffle,
  with pre/post seed, normalized arguments, result, and an owner-assigned label
  for omitted team gender, move accuracy, critical hits, damage rolls, Gen 3
  Quick Claw rolls, and action-queue ties. Other draws are explicitly prefixed
  `unlabeled:` and retain
  their `event:effect:move` diagnostic context;
- `effect`: move-owned boost, status-set, and status-cure operations at their
  semantic execution boundary. Each record identifies primary, secondary, or
  self-secondary phase and preserves explicit blocked/clamped no-change
  attempts. Boost payloads are one record per stat with requested delta and
  before/after stages; status payloads carry before/after status IDs. Secondary
  chance draws remain PRNG records labeled `move.secondary`.
  Recoil and drain records are emitted after damage with the actual damage
  basis, fraction, requested amount, HP delta, and applied result. Rock Head's
  `Damage` handler emits a separate preceding `prevent-recoil` cause record;
  the following recoil result remains present with zero applied damage.
  Multi-hit moves emit a sampled plan, one chronological record per completed
  hit with ordinal/critical/damage-roll/damage, and a final actual count plus
  stop reason. The owned count sample is labeled `move.multihit_count`.
  Fixed damage emits its tagged formula and resolved amount immediately before
  returning from `getDamage`; it therefore has no critical or damage-roll draw.
  Gen 3 Reversal emits its HP ratio, bracket, and resolved base power inside
  the generation override, then continues through ordinary damage PRNG stages.
- `handlers`: the complete handler list immediately after Showdown performs its
  event-specific ordering, with effect, holder, order, priority, sub-order,
  effect-order, and speed.
- `immunity`: the result of ordinary move-type immunity resolution at
  `Pokemon.runImmunity`, after Ground grounding or type-chart resolution. It
  records the target, attacking type, and `none`, `type`, or `ability`; only an
  ability result carries an effect ID (`levitate`). This is a distinct semantic
  boundary, not a Showdown event handler. In particular, Showdown implements
  Levitate through its grounding query, so the existing raw `handlers` record
  remains the authority for actual `TryHit` discovery and ordering.
- `modifier`: each projected numeric modifier handler records the relay value
  and Q12 accumulator before and after the callback; a final record captures
  Showdown's single application of the accumulated modifier. The projection
  includes the final `ModifyDamage` boundary used by Fly, Dig, and Dive, which
  is distinct from `ModifyDamagePhase1`. This distinguishes both accumulating
  modifiers such as Guts plus Black Belt and generation-specific staging such
  as semi-invulnerable double damage.
- `damage-stage`: the Gen 3 built-in burn stage records damage before and after,
  Q12 multiplier 2048, whether it applied, and the suppression reason. It is
  emitted only for burned attackers. Burn is deliberately not presented as an
  event handler: Gen 3 performs it directly in `modifyDamage`, where Guts can
  suppress it.
- `decision`: a stable decision-boundary ordinal, normalized per-side request
  kind and legal choices, a private canonical state projection, and the
  protocol lines produced since the preceding decision boundary. Volatile
  clock lines are omitted from the protocol slice. The canonical Pokémon item
  lifecycle includes current item, `lastItem`, `usedItemThisTurn`, `ateBerry`,
  and Gen 3's persistent `itemKnockedOff` slot lockout.
- `queue`: normalized submitted choices and the sorted move/switch actions at
  the point Showdown has completed queue construction, before execution.

Records form a discriminated union with a contiguous sequence number. Tracing
is disabled unless `PS_GEN3_VERIFY_TRACE=1`. With tracing disabled the observer
is null and the original PRNG and event paths execute unchanged. With tracing
enabled the observer reads state after each draw, ordering operation, modifier
callback, or burn stage; it does not perform a draw, sort a list, alter relay
values, or emit battle protocol.

The boundary driver may install a fixture's explicit initial `brn` state after
team construction. It initializes Showdown's status state directly and updates
the already-recorded initial decision snapshot. This represents canonical
initial state; it intentionally does not simulate a move or emit a status
protocol event.

`oracle_smoke.js` runs a fixed Gen 3 move battle, focused Guts plus Black Belt
and ordinary burn checks, plus
`seed42-battle04-forced-replacement`. It requires the one-sided
`wait/switch` boundary followed by the post-replacement `move/move` boundary,
and compares the complete observation to a frozen SHA-256. This proves patch
application and deterministic observation only. It does not compare the
native engine, so it awards no semantic points.

Stable phase is projected through each decision's request kind; finer internal
phase instrumentation and native handler-list comparison remain future work.
The manifest validator also currently reports incomplete required mappings.
Those limitations remain explicit in `score.json`.
