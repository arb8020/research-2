#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const display = new Map([
  ['lanturn', 'Lanturn'], ['raikou', 'Raikou'], ['voltabsorb', 'Volt Absorb'],
  ['pressure', 'Pressure'],
  ['thunderbolt', 'Thunderbolt'], ['thunderwave', 'Thunder Wave'],
  ['tackle', 'Tackle'],
]);
const name = id => display.get(id) || id;
const mon = (species, gender, ability, moves, stats, initial_hp) => ({
  species, level: 100, gender, ability, item: '', moves, stats, status: null,
  ...(initial_hp === undefined ? {} : {initial_hp}),
});
const target = initialHP => mon(
  'lanturn', 'M', 'voltabsorb', ['tackle'], [391, 152, 152, 188, 188, 170],
  initialHP);

function writeTeam(filename, pokemon) {
  const text = pokemon.map(p => [
    `${name(p.species)}${p.gender === 'N' ? '' : ` (${p.gender})`}`,
    `Ability: ${name(p.ability)}`,
    'Level: 100',
    'Hardy Nature',
    ...p.moves.map(move => `- ${name(move)}`),
    '',
  ].join('\n')).join('\n');
  fs.writeFileSync(path.join(out, filename), text);
}

function writeCase(id, attacker, defender) {
  const left = `${id}-p1.txt`;
  const right = `${id}-p2.txt`;
  writeTeam(left, [attacker]);
  writeTeam(right, [defender]);
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/mods/gen3/abilities.ts; data/mods/gen3/scripts.ts',
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [
      {source: left, normalized: [attacker]},
      {source: right, normalized: [defender]},
    ],
    source_choices: [['move 1', 'move 1']],
    choices: [['move 1', 'move 1']], forced_outcomes: [],
    features: [
      'choice.move', 'handler.try-hit', 'handler.volt-absorb',
      'hit.accuracy', 'hit.immunity-cause', 'prng.labeled',
      'queue.speed', 'state.canonical',
    ],
    boundaries: [
      'request', 'choice', 'queue', 'handlers', 'immunity', 'state',
      'events', 'prng',
    ],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(
    path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

writeCase(
  'volt-absorb-thunderbolt-heal',
  mon('raikou', 'N', 'pressure', ['thunderbolt'], [321, 206, 186, 266, 236, 266]),
  target(191));
writeCase(
  'volt-absorb-thunderbolt-full',
  mon('raikou', 'N', 'pressure', ['thunderbolt'], [321, 206, 186, 266, 236, 266]),
  target());
writeCase(
  'volt-absorb-thunder-wave-exclusion',
  mon('raikou', 'N', 'pressure', ['thunderwave'], [321, 206, 186, 266, 236, 266]),
  target());
