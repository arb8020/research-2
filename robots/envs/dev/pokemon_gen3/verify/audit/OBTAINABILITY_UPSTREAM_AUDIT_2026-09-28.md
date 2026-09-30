# Gen 3 OU obtainability upstream audit

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The independent audit compared `TeamValidator.validateSet`, `validateMoves`,
`checkCanLearn`, `validateSource`, `validateEvent`, `findEggMoveFathers`, and
`fatherCanLearn` with the native admission boundary. Its initial probes found
three native divergences:

- level-1 Nidoking was accepted because native code checked only Nidoking's
  own evolution level, not Nidorino's lineage gate;
- level-1 Articuno was accepted because event-only species origins were not
  represented when every move was otherwise unrestricted;
- Hitmontop with High Jump Kick and Mach Punch was rejected because the father
  search collapsed each move to independent egg/non-egg booleans too early.

The integrated corrections are reusable boundaries:

- the acquisition solver computes the effective evolution minimum across the
  generated lineage and permits only a matching event witness below it;
- generated species descriptors carry a bounded event-only source domain,
  intersected with exact move events and validated even for unrestricted moves;
- generated level-up-as-egg descriptors include the male-mother predicate, and
  the bounded father recursion retains a one-egg terminal product instead of
  requiring every father move to be independently unrestricted;
- Undiscovered hatch species use their evolution's breeding group, matching
  Showdown's baby-species boundary.

Persistent differential cases now cover those three former divergences plus
exact Gengar event gender/nature/IV fields, Articuno's event minimum, the
Shedinja Gust regression, incompatible Skarmory and Armaldo egg pairs,
male/female/genderless level-up egg sources, Field/Smeargle egg delegation,
event ability reroll/slot handling, event-plus-unrestricted source
intersection, future Virtual Console rejection, and omitted Hidden Power type
derivation. The focused admission gate is 136/136 exact with deterministic
replay.

## Source-domain conclusion

The pinned Gen 3 Dex contains exactly 20,195 legal Gen 3 method records over
18,293 positive-number species/move rows: 8,927 machine, 5,456 tutor, 3,751
level, 1,082 event, 974 egg, and 5 restricted records. It contains no legal
Gen 1/2 record for Gen 3 OU. `PokemonSources.sourcesBefore` is a symbolic union
of nonexclusive sources, not permission to vendor older learnsets. The
generator now rejects any unexpected legal pre-Gen-3 source instead of silently
changing that assumption.

Tradeback, enabled Mimic-glitch behavior, and the level-100 event EV branch are
unreachable in the resolved stock format. The latter's Gen 3 events
have unrestricted alternative move sources, so no source selection can force
that event validation branch.

Zigzagoon Belly Drum plus Extreme Speed is legal at the stock format's default
level 100, which is what the older persistent fixture proves. At level 5 the
pinned validator rejects it in stock Gen 3 OU and accepts it only under
`gen3ou@@@pomegglitchclause`: Belly Drum becomes a synthetic Pomeg egg source
and combines with Extreme Speed's Emerald event-egg source. The exact admission
pair now records both outcomes; the earlier audit conflated the two levels.

This audit closes the identified source-shape gaps. It does not by itself
promote `obtainablemoves` or `obtainablemisc`; randomized recombination remains
an independent proof obligation.
