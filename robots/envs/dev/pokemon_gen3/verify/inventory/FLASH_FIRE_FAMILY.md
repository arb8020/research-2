# Flash Fire activation lifecycle

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This slice closes the seven reachable Flash Fire records through one
ability-owned activation condition, not through Fire-move resolvers:

- `ability:flashfire`;
- `condition:volatiles.flashfire`;
- `event_hook:ability.flashfire.onTryHit`;
- `event_hook:ability.flashfire.onEnd`;
- `event_hook:ability.flashfire.condition.onStart`;
- `event_hook:ability.flashfire.condition.onModifyDamagePhase1`;
- `event_hook:ability.flashfire.condition.onEnd`.

## Resolved semantics

The resolved Gen 3 definition is inherited through
`data/abilities.ts#flashfire`, `data/mods/gen4/abilities.ts#flashfire`, and
`data/mods/gen3/abilities.ts#flashfire`. The Gen 3 hit pipeline is in
`data/mods/gen3/scripts.ts`.

After invulnerability, type checks, and accuracy, target-side `TryHit`
intercepts an opposing Fire move. It declines interception while the holder is
frozen. It also declines Gen 3 Will-O-Wisp when the target is Fire typed,
already statused, or behind Substitute. Otherwise it adds the durationless,
no-copy Flash Fire volatile and returns null. The first add runs condition
Start; a duplicate add has no Restart, emits ability immunity, and still
returns null. An absorbed hit owns no critical, damage-roll, or secondary PRNG.

The installed condition multiplies Fire damage by 1.5 at
`ModifyDamagePhase1`. It applies only while the holder still has the ability.
Ability End removes the volatile and condition End is silent. Switching,
fainting, and ability replacement therefore share the ordinary owner
lifecycle; Baton Pass must not copy the condition.

The upstream Gen 3 frozen regression has a misleading title. Its assertion
proves suppression: the frozen holder takes Fire damage and normally thaws.

## Native boundary

Generated data supplies:

- a target ability `TryHit` program;
- a durationless volatile descriptor with Start, End, and
  `ModifyDamagePhase1` handlers;
- an ability End cleanup program;
- a move semantic tag for the Gen 3 Will-O-Wisp admission exception.

The generic interpreter supplies only reusable operations:

- require the holder status not to match a generated mask;
- for a tagged major-status move, require that the target can receive that
  status with respect to generated type, current status, and Substitute gates;
- add/restart a generated holder volatile;
- require an ability-installed condition's source ability still to be the
  holder's current ability;
- remove an ability-installed holder volatile on owner End;
- chain a generated Q12 damage modifier.

Validation resolves volatile descriptors through the plugin bundle rather
than comparing against a historical named enum maximum. Invalid programs must
fail before mutation or PRNG consumption.

## Proof basis

Legal differential cases use Ponyta, Charizard, Dusclops, and existing moves:

1. first activation, repeated absorption, persistent condition, and boosted
   outgoing Fire damage;
2. frozen fallthrough, damage, thaw, and no activation;
3. Will-O-Wisp against a native Fire-type Flash Fire holder, proving the
   generated exception bypasses interception;
4. Protect prevents activation, while an ordinary damaging Fire move against
   Substitute activates before Substitute interception;
5. switching removes activation and returning does not restore it.

Focused C tests additionally cover activation and duplicate admission without
damage-stage draws, frozen fallthrough, the Fire-holder Will-O-Wisp exception,
exact Q12 relay staging, ability replacement cleanup, and no-copy metadata.
Skill Swap and Baton Pass are separate unsupported families and are not
required as differential fixtures.

Only after focused, differential, full-corpus, deterministic replay, random,
Ocean, sanitizer, generator, and inventory gates pass may the seven records be
reclassified.
