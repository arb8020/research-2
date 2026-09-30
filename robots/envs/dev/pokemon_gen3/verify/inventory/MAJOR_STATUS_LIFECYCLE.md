# Gen 3 major-status lifecycle callbacks

Pinned Gen 3 inherits burn, poison, and Toxic callbacks through the resolved
mod chain. Burn and poison `Start` callbacks are protocol-only. Toxic `Start`
and `SwitchIn` set the owned stage counter to zero. The Gen 4 battle-action
override stages a returning Pokémon as `EntryHazard`, then `SwitchIn`, then
ability/item Start; residual work runs later.

Native generated data therefore supplies mutation-free burn/poison Start
descriptors plus Toxic Start and SwitchIn programs using the typed
`SET_HOLDER_STATUS_COUNTER` operation. The generic interpreter validates the
owner/status/event product, resets the Toxic stage, and emits the existing
condition-update trace only for a changed SwitchIn counter. The switch action
contains no status identity or residual-policy reset branch. Plugin ABI version
7 records the expanded typed counter-selector domain.

`status-primary-rotation` proves burn and poison Start discovery.
`toxic-switch-reset` proves Toxic Start, bench persistence, and reset on
return. `toxic-switch-in-hazard-order` additionally proves that Spikes damage
and its handler occur before Toxic SwitchIn/reset, which occurs before Toxic's
next residual increment. These fixtures and the focused status tests map all
four callbacks to Pokémon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
