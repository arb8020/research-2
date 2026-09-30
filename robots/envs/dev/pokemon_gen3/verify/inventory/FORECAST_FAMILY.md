# Forecast and mutable weather-form projection

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Forecast closes one ability and its `onStart` and `onWeatherChange` hooks. It
does not add a Forecast identity branch to the battle kernel. Generated Gen 3
data supplies two ordinary handlers plus one immutable weather-form policy:

- `Start` delegates to the holder's `WeatherChange` callback;
- `WeatherChange` projects clear, sun, rain, or hail current identity and type
  from effective weather;
- projection is restricted to the generated base-form family, active holders,
  and non-transformed state.

The generic kernel now distinguishes Showdown's two real event operations:
`singleEvent` invokes one owner's callback without constructing a discovery
list, while `eachEvent` orders the active Pokémon and discovers handlers for
each target. Weather installation, replacement, expiry, and Cloud Nine End use
the latter. This distinction owns the labeled
`each_event.weatherchange.active_order` draw.

`PokemonMutable.species_id` is current battle-time identity; the immutable set
retains base identity. Switch teardown restores the generated base profile.
The present Gen 3 form policy is admitted only when all four generated forms
share a source family and base stats, so projection can honestly preserve the
calculated stat vector. A later generation whose forms change stats must
provide a stronger typed capability rather than reusing this policy.

Authoritative source:

- `data/abilities.ts#forecast`: Start delegation, transformed/active guards,
  effective-weather selection, and form changes;
- `data/mods/gen3/abilities.ts#forecast`: inherited Gen 3 descriptor;
- `sim/field.ts#setWeather`, `clearWeather`, and `effectiveWeather`: field-wide
  WeatherChange dispatch and suppression;
- `data/mods/gen4/abilities.ts#cloudnine` as inherited by Gen 3: Start does not
  notify WeatherChange, while End does.

Focused native evidence:

- `native/test_pokemon.c#test_generated_weather_form_projection` proves clear
  and sunny projection, the transformed guard, and atomic rejection of base/
  clear mismatch, duplicate form IDs, missing forms, and unequal form stats.

Differential evidence:

- `forecast-weather-cycle-expiry` covers sun/rain/hail/sand projection,
  replacement, failed same-weather refresh, and expiry;
- `forecast-switch-start-reset` covers Start under stored weather, switch
  reset, re-entry, and expiry;
- `forecast-cloud-nine-suppression` covers Gen 3's deliberately asymmetric
  Cloud Nine Start/End behavior and a real weather change under suppression;
- `forecast-weatherchange-order` covers equal-speed active ordering and the
  labeled PRNG draw.

All 24 new boundaries and the complete 2,917-boundary corpus agree with the
pinned oracle. Oracle and native replay are deterministic. Classification is
therefore 1,070 implemented, 426 inert, 37 unreachable, and 27 unsupported.
