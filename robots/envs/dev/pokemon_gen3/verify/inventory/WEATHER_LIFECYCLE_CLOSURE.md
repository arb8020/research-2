# Generated weather lifecycle closure

Pinned Showdown represents Hail, Rain Dance, Sandstorm, and Sunny Day as field
conditions with five-turn `FieldStart`/`FieldResidual`/`FieldEnd` lifecycles.
Hail and Sandstorm additionally own `Weather` damage callbacks. The native
generation bundle flattens these facts into immutable `PokemonWeatherPolicy`
rows; generic field-state installation, replacement, residual execution, and
expiry consume those rows without weather-name branches.

Focused tests cover install, replacement, failed refresh, residual order 8,
generated type-immunity masks, damage, effective-weather suppression, and
expiry. Legal differential cases now run every weather through start and
residual boundaries and run Hail, Rain, Sandstorm, and Sun through natural
expiry or replacement. Hail's fixture was extended through its complete
five-turn lifetime.

Sunny Day's separate freeze `Immunity` callback is proven by a legal
Sunny-Day-before-Ice-Beam case with a reached secondary and rejected status.
Focused native evidence additionally proves Cloud Nine suppresses that
effective-weather immunity without clearing stored weather. Ability-owned Sand
Veil immunity remains separate from natural weather type immunity.
