#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const mon = (species, ability, moves, stats, gender = 'M') => ({
  species, level: 100, gender, ability, item: '', moves, stats, status: null,
});
const castform = moves => mon('castform', 'forecast', moves,
  [281, 176, 176, 176, 176, 176]);
const blissey = (moves = ['splash'], speed = 146) => mon(
  'blissey', 'naturalcure', moves, [651, 56, 56, 186, 306, speed], 'F');
const smeargle = moves => mon('smeargle', 'owntempo', moves,
  [251, 76, 106, 76, 126, 186]);
const golduck = moves => mon('golduck', 'cloudnine', moves,
  [301, 200, 192, 226, 196, 206]);

const names = {
  castform: 'Castform', forecast: 'Forecast', blissey: 'Blissey',
  naturalcure: 'Natural Cure', smeargle: 'Smeargle', owntempo: 'Own Tempo',
  golduck: 'Golduck', cloudnine: 'Cloud Nine', sunnyday: 'Sunny Day',
  raindance: 'Rain Dance', hail: 'Hail', sandstorm: 'Sandstorm',
  splash: 'Splash', rest: 'Rest',
};
const name = id => names[id] || id[0].toUpperCase() + id.slice(1);

function writeTeam(file, pokemon) {
  const team = Array.isArray(pokemon) ? pokemon : [pokemon];
  const blocks = team.map(value => {
    const lines = [`${name(value.species)} (${value.gender})`,
      `Ability: ${name(value.ability)}`, 'Level: 100'];
    if (value.stats[5] === 176 && value.species === 'blissey') {
      lines.push('EVs: 120 Spe');
    }
    lines.push('Hardy Nature');
    for (const move of value.moves) lines.push(`- ${name(move)}`);
    return lines.join('\n');
  });
  fs.writeFileSync(path.join(out, file), `${blocks.join('\n\n')}\n`);
}

function make(id, p1, p2, choices, testName, sourceChoices = choices) {
  const left = Array.isArray(p1) ? p1 : [p1];
  const right = Array.isArray(p2) ? p2 : [p2];
  const a = `${id}-p1.txt`, b = `${id}-p2.txt`;
  writeTeam(a, left);
  writeTeam(b, right);
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/abilities.ts#forecast; data/mods/gen3/abilities.ts#forecast; sim/field.ts',
      test_name: testName, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: a, normalized: left}, {source: b, normalized: right}],
    source_choices: sourceChoices, choices, forced_outcomes: [],
    features: ['ability.forecast', 'choice.move', 'state.canonical',
      'state.form-overlay', 'condition.weather'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`),
    `${JSON.stringify(fixture, null, 2)}\n`);
}

make('forecast-weather-cycle-expiry',
  castform(['sunnyday', 'raindance', 'hail', 'sandstorm']), blissey(),
  [1, 2, 3, 4, 1, 1, 1, 1, 1].map(slot => [`move ${slot}`, 'move 1']),
  'Forecast projects effective types across weather replacement, neutral sand, failed refresh, and expiry');

make('forecast-switch-start-reset',
  [smeargle(['sunnyday', 'splash']), castform(['rest'])], blissey(),
  [['move 1', 'move 1'], ['switch 2', 'move 1'], ['switch 1', 'move 1'],
    ['switch 2', 'move 1'], ['move 1', 'move 1']],
  'Forecast Start projects under existing weather; switch-out restores base identity; expiry projects clear',
  [['move 1', 'move 1'], ['switch 2', 'move 1'], ['switch 2', 'move 1'],
    ['switch 2', 'move 1'], ['move 1', 'move 1']]);

make('forecast-cloud-nine-suppression', castform(['sunnyday', 'raindance', 'rest']),
  [golduck(['splash']), smeargle(['splash'])],
  [['move 1', 'move 1'], ['move 3', 'switch 2'], ['move 3', 'switch 1'],
    ['move 2', 'move 1'], ['move 3', 'switch 2']],
  'Gen 3 Cloud Nine Start does not notify Forecast; real weather changes and Cloud Nine End use effective weather',
  [['move 1', 'move 1'], ['move 3', 'switch 2'], ['move 3', 'switch 2'],
    ['move 2', 'move 1'], ['move 3', 'switch 2']]);

make('forecast-weatherchange-order', castform(['sunnyday']), blissey(['splash'], 176),
  [['move 1', 'move 1']],
  'equal-speed WeatherChange traversal has one labeled active-order draw');
