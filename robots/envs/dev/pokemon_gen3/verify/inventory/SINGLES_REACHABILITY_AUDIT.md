# Gen 3 OU singles reachability and inert-callback audit

This audit removes five false unsupported claims without pretending to execute
callbacks whose observable denotation is empty or whose owner state cannot be
constructed. The generator pins each inheritance/topology premise against
Showdown commit `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

- `move.helpinghand.onTryHit` is unreachable. Helping Hand targets an adjacent
  ally; the pinned singles format has none, so target normalization rejects the
  action before the callback. `target-adjacent-ally-no-target` is the legal
  differential witness.
- `move.toxic.condition.onSourceAccuracy` and
  `onSourceInvulnerability` are unreachable inheritance debris. Effective
  Gen 3 Toxic retains the nested condition but has no `onPrepareHit`,
  `volatileStatus`, or callback which installs that condition.
- `move.splash.onTry` and `onTryHit` are observationally inert. The former only
  rejects under Gravity, which no Gen 3 descriptor can establish; the latter
  only emits protocol text outside the canonical native contract. Existing
  legal Splash actions prove PP/action/state behavior without hidden PRNG or
  state effects.

These classifications are format-scoped. They do not assert that the same
callbacks are unreachable or inert in doubles or later generations.
