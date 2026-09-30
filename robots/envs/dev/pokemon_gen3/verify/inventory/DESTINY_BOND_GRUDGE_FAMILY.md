# Destiny Bond and Grudge semantic family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
Format: `gen3ou` singles. The source of truth is pinned Showdown, not a
mechanics guide.

## Semantic boundary

These moves install self volatiles whose payoff is dispatched by the user's
later `Faint` event. They are one family at installation and lifecycle, but
their payoffs are distinct:

- Destiny Bond faints the opposing source when a non-Future-Move move directly
  causes the holder to faint.
- Grudge sets every move slot matching the source's `lastMove` to zero PP when
  such a move directly causes the holder to faint and the source remains
  alive.
- Before the holder attempts another move, either volatile is removed. Destiny
  Bond's `onPrepareHit` removes the old instance before the new one is
  installed, so consecutive Gen 3 use refreshes the volatile and succeeds.
- Ordinary switching and faint cleanup are generic volatile lifecycle, not
  bespoke move behavior. Baton Pass must not copy Destiny Bond (`noCopy`).

The reusable state is only the volatile's presence on its holder. Damage
history does not belong to either move. The `Faint` dispatch must preserve the
fainting effect and source; reconstructing causality from `lastMove` alone is
incorrect.

## Source evidence

At the pinned revision:

- `data/moves.ts#destinybond` owns `onPrepareHit`, `onStart`, `onFaint`,
  priority `-1` `onBeforeMove`, and `onMoveAborted`.
- `data/moves.ts#grudge` owns `onStart`, `onFaint`, and priority `100`
  `onBeforeMove`.
- `sim/battle-actions.ts` supplies the move effect/source to damage and faint
  processing; `sim/pokemon.ts` owns volatile removal during switch and faint.
- `test/sim/moves/destinybond.js:11`, `:32`, and `:43` are useful assertion
  shapes, but run the default generation. They are not direct Gen 3 evidence;
  the derived fixtures below resolve `gen3ou` explicitly.

Gen 3 resolves through the inherited `onPrepareHit` implementation in the
pinned mod chain. The effective resolved descriptor, rather than a guessed
generation cutoff, is authoritative.

## Derived evidence

`generate-destiny-bond-grudge-cases.js` checks the exact Showdown revision,
validates both imported teams with `TeamValidator.get('gen3ou')`, and emits 13
cases:

| Case | Oracle behavior |
| --- | --- |
| `destiny-bond-direct-move-ko` | Quick Attack KOs the holder; both holder and opposing source faint. |
| `destiny-bond-before-move-cleanup` | The holder attempts Splash first; Swift then KOs only the holder. |
| `destiny-bond-consecutive-refresh` | The second use replaces the old volatile with a fresh instance; the later direct KO ends with both sides fainting. |
| `grudge-direct-move-ko` | Quick Attack KOs the holder and its PP becomes zero. |
| `grudge-before-move-cleanup` | The holder attempts Splash first; Swift KOs it and retains ordinary post-use PP (`31/32`). |
| `grudge-source-fainted-exclusion` | Self-Destruct KOs both battlers; its PP remains ordinary post-use PP (`7/8`) because the source is already fainted. |
| `destiny-bond-future-sight-exclusion` | A Future Sight KO dispatches Faint but does not faint its source. |
| `destiny-bond-doom-desire-exclusion` | A Doom Desire KO dispatches Faint but does not faint its source. |
| `grudge-future-sight-exclusion` | A Future Sight KO leaves the source move's ordinary spent PP intact. |
| `grudge-doom-desire-exclusion` | A Doom Desire KO leaves the source move's ordinary spent PP intact. |
| `destiny-bond-indirect-faint-exclusion` | Burn residual faints the holder without retaliating. |
| `grudge-indirect-faint-exclusion` | Burn residual faints the holder without changing opposing PP. |
| `destiny-bond-move-aborted-cleanup` | A labeled full-paralysis outcome dispatches MoveAborted and removes Destiny Bond. |

The consecutive Destiny Bond result is intentionally recorded from the
observable state and later faint result, not inferred from the handler's
surface shape. Native behavior must match that denotation unless the oracle pin
changes.

The generator accepts an optional output directory so probes can remain out of
tree:

```sh
node verify/cases/generate-destiny-bond-grudge-cases.js \
  /path/to/pinned-showdown /tmp/destiny-bond-grudge
```

## Promotion evidence

The 13-case basis covers every generated guard branch: direct move provenance,
both delayed move IDs, indirect fainting, a living or already-fainted source,
ordinary BeforeMove cleanup, consecutive refresh, and MoveAborted cleanup.
`test_faint_response_condition_family` proves the native payoff operations.
The generic volatile lifecycle tests prove switch cleanup, and the Baton Pass
transfer test proves descriptor-driven `noCopy` filtering; a Destiny Bond then
Baton Pass scenario cannot distinguish `noCopy` because BeforeMove removes the
volatile before transfer. The resolved generated descriptor supplies the
Destiny Bond `noCopy` binding.

Doubles ally-source behavior and Dynamax are unreachable in Gen 3 OU. Support
promotion still requires the ordinary full differential/replay and validation
gates; fixture generation alone is not evidence of native agreement.
