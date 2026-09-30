#!/usr/bin/env node
'use strict';

/* Deterministic descriptor rotation for the declarative Gen 3 direct-boost
 * family. Each battle is fresh, so this proves descriptor shape rather than
 * accidentally exercising stage caps. */
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const rows = [
  ['acidarmor', 'agility', 'amnesia', 'barrier'],
  ['bulkup', 'calmmind', 'cosmicpower', 'dragondance'],
  ['growth', 'harden', 'howl', 'irondefense'],
  ['meditate', 'sharpen', 'swordsdance', 'tailglow'],
  ['withdraw', 'charm', 'cottonspore', 'faketears'],
  ['featherdance', 'flash', 'kinesis', 'metalsound'],
  ['sandattack', 'scaryface', 'screech', 'smokescreen'],
  ['stringshot', 'sweetscent', 'tailwhip', 'tickle'],
  ['growl', 'leer'],
];
/* Pinned draws prove numeric accuracy (including 100) consumes exactly one
 * draw per targeted move. Rows 1-4 are accuracy:true and must consume none. */
const accuracyResults = [null, null, null, null,
  [2, 77, 87], [54, 11, 54, 34], [77, 15, 68, 45],
  [22, 36, 11, 88], [67, 57]];

const machop = moves => ({
  species: 'machop', level: 100, gender: 'M', ability: 'guts', item: '', moves,
  stats: [281, 196, 136, 106, 106, 106], status: null,
});
const magikarp = {
  species: 'magikarp', level: 100, gender: 'M', ability: 'swiftswim', item: '',
  moves: ['splash'], stats: [181, 56, 146, 66, 76, 196], status: null,
};
const outputDir = path.resolve(__dirname, 'derived');
for (let row = 0; row < rows.length; row++) {
  const moves = rows[row];
  const choices = moves.map((_, slot) => [`move ${slot + 1}`, 'move 1']);
  const value = {
    schema: 'pokemon-native-differential-case-v1',
    id: `boost-rotation-${row + 1}`,
    provenance: {
      kind: 'showdown-derived', source_file: 'sim/battle.ts',
      test_name: `Gen 3 direct-boost descriptor rotation row ${row + 1}`,
      oracle_revision: revision,
    },
    format: 'gen3ou', seed: [91, 17, 43, row === 5 ? 2 : row + 1],
    teams: [
      {source: `boost-rotation-${row + 1}-p1.txt`, normalized: [machop(moves)]},
      {source: 'magikarp-splash-p2.txt', normalized: [magikarp]},
    ],
    source_choices: choices, choices,
    forced_outcomes: (accuracyResults[row] || []).map((result, index) => ({
      label: 'move.accuracy', occurrence: index + 1, range: 100, result,
    })),
    features: ['effect.boost', 'hit.accuracy', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'state', 'events', 'prng'],
    limits: {max_boundaries: moves.length + 1, max_actions: moves.length * 2},
  };
  const filename = path.join(outputDir, `boost-rotation-${row + 1}.json`);
  fs.writeFileSync(filename, `${JSON.stringify(value, null, 2)}\n`);
  const team = [
    'Machop (M)', 'Ability: Guts', 'Level: 100',
    'EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe', 'Hardy Nature',
    ...moves.map(move => `- ${move}`), '',
  ].join('\n');
  fs.writeFileSync(path.join(outputDir, `boost-rotation-${row + 1}-p1.txt`), team);
}
