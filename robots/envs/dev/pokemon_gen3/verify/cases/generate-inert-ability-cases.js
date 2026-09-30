#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const rows = [
  ['illuminate', 'Illuminate', 'lanturn', 'surf', [391, 152, 152, 188, 188, 170]],
  ['pickup', 'Pickup', 'zigzagoon', 'tackle', [217, 96, 118, 96, 118, 156]],
  ['runaway', 'Run Away', 'ponyta', 'tackle', [241, 206, 146, 166, 166, 216]],
  ['stench', 'Stench', 'muk', 'sludge', [351, 246, 186, 166, 236, 136]],
];
const title = value => value.replace(/(^|\s)\S/g, c => c.toUpperCase());
for (const [ability, abilityName, species, move, stats] of rows) {
  const id = `inert-ability-${ability}`;
  const p1 = `${id}-p1.txt`;
  const p2 = `${id}-p2.txt`;
  fs.writeFileSync(path.join(out, p1), [
    `${title(species)} (M) @ Leftovers`, `Ability: ${abilityName}`, 'Level: 100',
    'EVs: 1 HP', 'Hardy Nature', `- ${title(move)}`, '',
  ].join('\n'));
  fs.writeFileSync(path.join(out, p2), [
    'Magikarp (M) @ Oran Berry', 'Ability: Swift Swim', 'Level: 100',
    'EVs: 1 HP', 'Hardy Nature', '- Splash', '',
  ].join('\n'));
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/abilities.ts; data/mods/gen4/abilities.ts; data/mods/gen8/abilities.ts',
      test_name: `${abilityName} resolves to a callback-free battle identity`,
      oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [
      {source: p1, normalized: [{species, level: 100, gender: 'M', ability,
        item: 'leftovers', moves: [move], stats, status: null}]},
      {source: p2, normalized: [{species: 'magikarp', level: 100, gender: 'M',
        ability: 'swiftswim', item: 'oranberry', moves: ['splash'],
        stats: [181, 56, 146, 66, 76, 196], status: null}]},
    ],
    source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
    forced_outcomes: [],
    features: ['catalog.species-static', 'choice.move', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}
