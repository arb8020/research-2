#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const mon = (species, ability, item, moves, stats) => ({
  species, level: 100, gender: 'M', ability, item, moves, stats, status: null,
});
const smeargle = (moves, item = '') => mon('smeargle', 'owntempo', item, moves,
  [251, 76, 106, 76, 126, 186]);
const splash = (species = 'blissey', ability = 'naturalcure', stats = [651, 56, 56, 186, 306, 146]) =>
  mon(species, ability, '', ['splash'], stats);

function name(id) {
  return ({weatherball: 'Weather Ball', sunnyday: 'Sunny Day', raindance: 'Rain Dance',
    sandstorm: 'Sandstorm', protect: 'Protect', owntempo: 'Own Tempo',
    naturalcure: 'Natural Cure', cloudnine: 'Cloud Nine', clearbody: 'Clear Body',
    hardstone: 'Hard Stone'}[id] || id[0].toUpperCase() + id.slice(1));
}
function writeTeam(file, pokemon) {
  const lines = [`${name(pokemon.species)} (M)${pokemon.item ? ` @ ${name(pokemon.item)}` : ''}`,
    `Ability: ${name(pokemon.ability)}`];
  lines.push('Level: 100', 'Hardy Nature');
  for (const move of pokemon.moves) lines.push(`- ${name(move)}`);
  fs.writeFileSync(path.join(out, file), `${lines.join('\n')}\n`);
}
function make(id, p1, p2, choices, testName) {
  const a = `${id}-p1.txt`, b = `${id}-p2.txt`;
  writeTeam(a, p1); writeTeam(b, p2);
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/mods/gen3/moves.ts; sim/battle-actions.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: a, normalized: [p1]}, {source: b, normalized: [p2]}],
    source_choices: choices, choices, forced_outcomes: [],
    features: ['choice.move', 'state.canonical', 'condition.weather'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

make('weather-ball-clear', smeargle(['weatherball']), splash(), [['move 1', 'move 1']], 'clear Weather Ball is Normal 50 power');
for (const [label, setter] of [['sun', 'sunnyday'], ['rain', 'raindance'], ['sand', 'sandstorm'], ['hail', 'hail']]) {
  make(`weather-ball-${label}`, smeargle(['splash', 'weatherball']),
    mon('blissey', 'naturalcure', '', [setter, 'splash'], [651, 56, 56, 186, 306, 146]),
    [['move 1', 'move 1'], ['move 2', 'move 2']], `${label} mutates Weather Ball type, category, and power`);
}
make('weather-ball-cloud-nine', smeargle(['splash', 'weatherball']),
  mon('golduck', 'cloudnine', '', ['raindance', 'splash'], [301, 200, 192, 226, 196, 206]),
  [['move 1', 'move 1'], ['move 2', 'move 2']], 'Cloud Nine suppresses the effective weather mutation');
make('weather-ball-replacement-expiry', smeargle(['splash', 'weatherball']),
  mon('blissey', 'naturalcure', '', ['raindance', 'sunnyday', 'splash'], [651, 56, 56, 186, 306, 146]),
  [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 2', 'move 3'], ['move 1', 'move 3'],
   ['move 1', 'move 3'], ['move 1', 'move 3'], ['move 1', 'move 3'], ['move 2', 'move 3']],
  'Weather Ball observes replacement weather and clear weather after expiry');
make('weather-ball-stab-effectiveness', smeargle(['splash', 'weatherball']),
  mon('metagross', 'clearbody', '', ['sunnyday', 'splash'], [301, 306, 296, 226, 216, 176]),
  [['move 1', 'move 1'], ['move 2', 'move 2']], 'mutated Fire type drives effectiveness while clear Normal receives Smeargle STAB');
make('weather-ball-category', smeargle(['splash', 'weatherball']),
  mon('blissey', 'naturalcure', '', ['sandstorm', 'splash'], [651, 56, 56, 186, 306, 146]),
  [['move 1', 'move 1'], ['move 2', 'move 2']], 'sand Weather Ball remains physical in Gen 3');
make('weather-ball-protect', smeargle(['splash', 'weatherball']), mon('persian', 'limber', '', ['sunnyday', 'protect'], [271, 176, 156, 166, 166, 266]),
  [['move 1', 'move 1'], ['move 2', 'move 2']], 'Protect blocks the already-mutated Weather Ball');
make('weather-ball-substitute', smeargle(['splash', 'weatherball']), mon('persian', 'limber', '', ['sunnyday', 'substitute'], [271, 176, 156, 166, 166, 266]),
  [['move 1', 'move 1'], ['move 2', 'move 2']], 'Substitute absorbs the already-mutated Weather Ball');
make('weather-ball-type-item', smeargle(['splash', 'weatherball'], 'hardstone'),
  mon('blissey', 'naturalcure', '', ['sandstorm', 'splash'], [651, 56, 56, 186, 306, 146]),
  [['move 1', 'move 1'], ['move 2', 'move 2']], 'Hard Stone observes Weather Ball mutated Rock type');
