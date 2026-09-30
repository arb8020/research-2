#!/usr/bin/env node
'use strict';

/* Descriptor rotation for ordinary Gen 3 multi-hit moves.  Bone Rush's
 * existing differential family proves the shared gates and weighted law;
 * these cases prove every additional flattened row and fixed-count staging. */
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const outputDir = path.resolve(__dirname, 'derived');
const rows = [
  ['armthrust', 1], ['barrage', 36], ['bonemerang', 1],
  ['bulletseed', 1], ['cometpunch', 36], ['doublekick', 36],
  ['doubleslap', 1], ['furyattack', 36], ['furyswipes', 1],
  ['iciclespear', 36], ['pinmissile', 1], ['rockblast', 36],
  ['spikecannon', 1],
];
const p2 = {
  species: 'blissey', level: 100, gender: 'F', ability: 'naturalcure', item: '',
  moves: ['splash'], stats: [651, 56, 56, 186, 306, 146], status: null,
};
const p2File = 'multihit-rotation-blissey-p2.txt';
fs.writeFileSync(path.join(outputDir, p2File),
  'Blissey (F)\nAbility: Natural Cure\nLevel: 100\nHardy Nature\n- Splash\n');

for (const [move, seedTail] of rows) {
  const fixed = move === 'bonemerang' || move === 'doublekick';
  const id = `multihit-rotation-${move}`;
  const p1 = {
    species: 'smeargle', level: 100, gender: 'M', ability: 'owntempo', item: '',
    moves: [move], stats: [251, 76, 106, 76, 126, 186], status: null,
  };
  const p1File = `${id}-p1.txt`;
  fs.writeFileSync(path.join(outputDir, p1File),
    `Smeargle (M)\nAbility: Own Tempo\nLevel: 100\nHardy Nature\n- ${move}\n`);
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/mods/gen3/scripts.ts:411-480',
      test_name: `Gen 3 ordinary multi-hit descriptor: ${move}`,
      oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, seedTail],
    teams: [
      {source: p1File, normalized: [p1]},
      {source: p2File, normalized: [p2]},
    ],
    source_choices: [['move 1', 'move 1']],
    choices: [['move 1', 'move 1']],
    forced_outcomes: [],
    features: [
      'choice.move', 'damage.gen3', 'hit.multihit', 'prng.labeled',
      ...(fixed ? [] : ['prng.multihit']), 'state.canonical',
    ],
    boundaries: [
      'request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng',
      'terminal',
    ],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(
    path.join(outputDir, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}
