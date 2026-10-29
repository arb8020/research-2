#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const p1Source = 'smeargle-facade-p1.txt';
const p2Source = 'blissey-toxic-p2-item-target.txt';

fs.writeFileSync(path.join(out, p1Source), [
  'Smeargle (M)', 'Ability: Own Tempo', 'Level: 100', 'Hardy Nature',
  '- Facade', '',
].join('\n'));

const smeargle = status => ({
  species: 'smeargle', level: 100, gender: 'M', ability: 'owntempo', item: '',
  moves: ['facade'], stats: [251, 76, 106, 76, 126, 186], status,
});
const blissey = {
  species: 'blissey', level: 100, gender: 'F', ability: 'naturalcure', item: '',
  moves: ['splash'], stats: [651, 56, 56, 186, 306, 146], status: null,
};

for (const [suffix, status] of [['clean', null], ['paralyzed', 'par']]) {
  const id = `facade-${suffix}`;
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived', source_file: 'data/moves.ts',
      test_name: status ? 'Facade doubles BasePower for non-sleep major status' :
        'Facade preserves BasePower without major status',
      oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [
      {source: p1Source, normalized: [smeargle(status)]},
      {source: p2Source, normalized: [blissey]},
    ],
    source_choices: [['move 1', 'move 1']],
    choices: [['move 1', 'move 1']], forced_outcomes: [],
    features: ['choice.move', 'damage.gen3', 'handler.base-power',
      'condition.nonvolatile-status', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}
