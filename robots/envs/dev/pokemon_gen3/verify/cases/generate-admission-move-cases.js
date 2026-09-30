#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const smeargle = (moves, initialHP) => ({
  species: 'smeargle', level: 100, gender: 'M', ability: 'owntempo', item: '',
  moves, stats: [251, 76, 106, 76, 126, 186], status: null,
  ...(initialHP === undefined ? {} : {initial_hp: initialHP}),
});
const blissey = {species: 'blissey', level: 100, gender: 'F',
  ability: 'naturalcure', item: '', moves: ['splash'],
  stats: [651, 56, 56, 186, 306, 146], status: null};
function writeTeam(filename, moves) {
  fs.writeFileSync(path.join(out, filename), [
    'Smeargle (M)', 'Ability: Own Tempo', 'Level: 100', 'EVs: 1 HP',
    'Hardy Nature', ...moves.map(move => `- ${move}`), '',
  ].join('\n'));
}
function writeCase(value) {
  fs.writeFileSync(path.join(out, `${value.id}.json`),
    `${JSON.stringify(value, null, 2)}\n`);
}

writeTeam('smeargle-flail-p1.txt', ['Flail']);
for (const [power, initialHP] of [[20, 173], [40, 89], [80, 53],
  [100, 27], [150, 11], [200, 6]]) {
  const id = `flail-bracket-${power}`;
  writeCase({
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived', source_file: 'data/mods/gen3/moves.ts',
      test_name: `Flail shares the Gen 3 HP bracket yielding power ${power}`,
      oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 7],
    teams: [
      {source: 'smeargle-flail-p1.txt', normalized: [smeargle(['flail'], initialHP)]},
      {source: 'blissey-toxic-p2-item-target.txt', normalized: [blissey]},
    ],
    source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
    forced_outcomes: [
      {label: 'move.accuracy', occurrence: 1, range: 100, result: 22},
      {label: 'move.critical', occurrence: 1, range: 16, result: 4},
      {label: 'move.damage_roll', occurrence: 1, range: 16, result: 12},
    ],
    features: ['damage.gen3', 'damage.variable-power', 'hit.resolved-power',
      'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'immunity', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  });
}

for (const [id, move, testName] of [
  ['admission-hyper-voice', 'hypervoice',
    'Hyper Voice is an ordinary Gen 3 allAdjacentFoes attack'],
  ['admission-vital-throw', 'vitalthrow',
    'Vital Throw is priority -1 and always hits without an accuracy draw'],
]) {
  const filename = `${id}-p1.txt`;
  writeTeam(filename, [move === 'hypervoice' ? 'Hyper Voice' : 'Vital Throw']);
  writeCase({
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived', source_file: 'data/moves.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [
      {source: filename, normalized: [smeargle([move])]},
      {source: 'blissey-toxic-p2-item-target.txt', normalized: [blissey]},
    ],
    source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
    forced_outcomes: [],
    features: ['choice.move', 'damage.gen3', 'hit.accuracy', 'prng.labeled',
      'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  });
}
