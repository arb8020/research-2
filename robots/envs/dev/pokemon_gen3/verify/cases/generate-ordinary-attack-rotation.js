#!/usr/bin/env node
'use strict';

/* Deterministic differential rotation for the callback-free, constant-power
 * Gen 3 attack family.  Every source set is legal in pinned Gen 3 OU and uses
 * an already-admissible ability. */
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const species = {
  bulbasaur: {name: 'Bulbasaur', gender: 'M', ability: 'overgrow', stats: [231, 134, 134, 166, 166, 126]},
  charizard: {name: 'Charizard', gender: 'M', ability: 'blaze', stats: [297, 204, 192, 254, 206, 236]},
  skarmory: {name: 'Skarmory', gender: 'M', ability: 'keeneye', stats: [271, 196, 316, 116, 176, 176]},
  blissey: {name: 'Blissey', gender: 'F', ability: 'naturalcure', stats: [651, 56, 56, 186, 306, 146]},
  heracross: {name: 'Heracross', gender: 'M', ability: 'guts', stats: [301, 286, 186, 116, 226, 206]},
  poliwrath: {name: 'Poliwrath', gender: 'M', ability: 'waterabsorb', stats: [321, 206, 226, 176, 216, 176]},
  spearow: {name: 'Spearow', gender: 'M', ability: 'keeneye', stats: [221, 156, 96, 98, 98, 176]},
  golem: {name: 'Golem', gender: 'M', ability: 'rockhead', stats: [301, 256, 296, 146, 166, 126]},
  kingler: {name: 'Kingler', gender: 'M', ability: 'hypercutter', stats: [251, 296, 266, 136, 136, 186]},
};
const rows = [
  ['cut', 'bulbasaur', ''],
  ['dragonclaw', 'charizard', 'dragonfang'],
  ['drillpeck', 'skarmory', ''],
  ['eggbomb', 'blissey', ''],
  ['hornattack', 'heracross', ''],
  ['hydropump', 'poliwrath', ''],
  ['megahorn', 'heracross', 'silverpowder'],
  ['megakick', 'charizard', ''],
  ['peck', 'spearow', ''],
  ['pound', 'blissey', ''],
  ['rockthrow', 'golem', 'hardstone'],
  ['slam', 'kingler', ''],
  ['vinewhip', 'bulbasaur', ''],
  ['visegrip', 'kingler', ''],
  ['waterfall', 'poliwrath', ''],
  ['watergun', 'poliwrath', ''],
];
const outputDir = path.resolve(__dirname, 'derived');

for (const [index, [move, speciesID, item]] of rows.entries()) {
  const holder = species[speciesID];
  const id = `ordinary-attack-${move}`;
  const features = ['choice.move', 'damage.gen3', 'hit.accuracy', 'prng.labeled', 'state.canonical'];
  if (item) features.push(
    holder.stats[1] >= holder.stats[3] ? 'handler.modify-attack' : 'handler.modify-special-attack',
    'handler.type-boost-item');
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived', source_file: 'data/moves.ts',
      test_name: `Gen 3 callback-free constant-power attack: ${move}`,
      oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, move === 'dragonclaw' ? 6 : 4],
    teams: [
      {source: `${id}-p1.txt`, normalized: [{
        species: speciesID, level: 100, gender: holder.gender,
        ability: holder.ability, item, moves: [move], stats: holder.stats,
        status: null,
      }]},
      {source: 'tyrogue-tackle-p2.txt', normalized: [{
        species: 'tyrogue', level: 100, gender: 'M', ability: 'guts', item: '',
        moves: ['tackle'], stats: [211, 106, 106, 106, 106, 106], status: null,
      }]},
    ],
    source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
    /* The critical row reuses the already-proven pinned seed. Other rows use
     * natural deterministic draws and are still compared draw-for-draw. */
    forced_outcomes: move === 'dragonclaw' ? [
      {label: 'move.critical', occurrence: 1, range: 16, result: 0},
      {label: 'move.damage_roll', occurrence: 1, range: 16, result: 8},
    ] : [],
    features,
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng', 'terminal'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(outputDir, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);

  const itemLine = item ? ` @ ${item}` : '';
  const team = [
    `${holder.name} (${holder.gender})${itemLine}`,
    `Ability: ${holder.ability}`,
    'Level: 100',
    'EVs: 1 HP',
    'Hardy Nature',
    `- ${move}`,
    '',
  ].join('\n');
  fs.writeFileSync(path.join(outputDir, `${id}-p1.txt`), team);
}
