# Gen 3 Lock-On family

Lock-On and Mind Reader are two declarative producers of the same source-bound
`lockon` volatile. At the pinned Showdown revision, their Gen 3 descriptors
use numeric 100 accuracy, reject a duplicate volatile in `onTryHit`, and attach
the target as source provenance in `onHit`. The installed condition lasts two
turns and returns literal `true` from `onSourceAccuracy` and numeric `0` from
priority-1 `onSourceInvulnerability` only while that provenance still names
the active target.

The native generator emits one source-bound volatile effect and four small
handler programs. The generic kernel owns installation, provenance, ordered
Accuracy and Invulnerability dispatch, expiry, and switch/faint cleanup. Type
and ability immunity and Protect remain independent later/earlier semantic
boundaries; there is no Lock-On- or Mind-Reader-specific runtime branch.

Focused evidence is
`native/test_pokemon.c#test_lock_on_source_bound_accuracy_and_invulnerability`.
The differential fixtures are `lock-on-alias-repeat-accuracy`,
`lock-on-semi-invulnerable`, `lock-on-protect-and-immunity`, and
`lock-on-switch-relations`. They match pinned Showdown at 21 boundaries and
cover the alias, duplicate rejection, semi-invulnerable targeting, ordinary
immunity/Protect preservation, expiry, owner cleanup, and stale target
provenance after switching.
