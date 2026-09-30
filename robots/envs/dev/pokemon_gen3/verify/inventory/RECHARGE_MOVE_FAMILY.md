# Gen 3 recharge move family

Blast Burn, Frenzy Plant, Hydro Cannon, and Hyper Beam are four declarative
producers of the same Showdown `mustrecharge` condition. At the pinned
revision, each resolved move has the recharge flag and a self volatile effect;
`data/conditions.ts` owns the forced Recharge action and priority-11
`BeforeMove` consumption.

The generator validates each producer and emits the same after-move
`ADD_VOLATILE` operation. The generic condition lifecycle, request projection,
queue normalization, and handler interpreter are unchanged. A focused native
test proves that all four descriptors point at that one semantic product.

Three legal two-turn fixtures use Charizard, Venusaur, and Blastoise to prove
the additional producers against pinned Showdown. Each connected hit installs
the condition, projects the synthetic forced choice without allowing a switch,
and consumes it on the following turn without another PP deduction.
