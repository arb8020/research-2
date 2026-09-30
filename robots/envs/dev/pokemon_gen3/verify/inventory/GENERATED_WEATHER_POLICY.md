# Generated weather policy boundary

Pinned Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The build-time generator resolves Sandstorm, Hail, Rain Dance, and Sunny Day
through `Dex.forGen(3)`. It asserts the inherited `FieldStart`, order-8
`FieldResidual`, and `FieldEnd` lifecycle, then emits immutable policies for
condition-owned residual damage, natural type immunity, and status immunity.
The generic kernel schedules weather lifecycle and evaluates those policies
through effective weather. Cloud Nine suppresses effects without erasing or
pausing stored weather.

Important source correction: ordinary weather replacement in
`sim/field.ts` overwrites the old state and invokes only the new
`FieldStart`; it does not invoke the old weather's `FieldEnd`. `FieldEnd`
belongs to explicit clear/expiry. The existing `weather-sun-replacement`
fixture proves this absence, while `weather-cloud-nine-switch` proves stored
Rain Dance duration continues under suppression.

`native/test_pokemon.c#test_weather_status_immunity_is_generated_and_suppressible`
proves Sunny Day freeze rejection, Cloud Nine suppression of that rejection,
plugin-policy substitution through the same kernel, and pre-mutation rejection
of duplicate or malformed policies. Full condition/hook classification is not
advanced until legal paired sun/freeze and residual suppress/resume fixtures
are added.

The legal Gen 3 OU audit found no missing weather-immunity kernel operation:
Sand Veil is format-banned, Air Lock is confined to Uber Rayquaza, and neither
has a legal positive battle trace. Natural Sand/Hail type immunity remains
weather-condition data; future formats that admit Sand Veil must represent it
as an ability-owned ordered immunity handler rather than folding it into the
condition mask.
