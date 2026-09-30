#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const gengar = {
  species: 'gengar', level: 100, gender: 'M', nature: 'hardy',
  ability: 'levitate', item: '', moves: ['nightmare', 'protect'],
  stats: [262, 166, 156, 296, 186, 256], status: null,
};
const smeargle = status => ({
  species: 'smeargle', level: 100, gender: 'M', nature: 'hardy',
  ability: 'owntempo', item: '', moves: ['splash'],
  stats: [253, 76, 106, 76, 126, 186], status,
  ...(status === 'slp' ? {
    status_state: {kind: 'sleep', time: 5, skipped_time: 0},
  } : {}),
});
const magikarp = {
  species: 'magikarp', level: 100, gender: 'M', nature: 'hardy',
  ability: 'swiftswim', item: '', moves: ['splash'],
  stats: [182, 56, 146, 66, 76, 196], status: null,
};
const seviper = {
  species: 'seviper', level: 100, gender: 'M', nature: 'hardy',
  ability: 'shedskin', item: '', moves: ['screech'],
  stats: [288, 236, 156, 236, 156, 166], status: 'slp',
  status_state: {kind: 'sleep', time: 5, skipped_time: 0},
};

fs.writeFileSync(path.join(out, 'gengar-nightmare-protect-p1.txt'), [
  'Gengar (M)', 'Ability: Levitate', 'Level: 100', 'EVs: 4 HP',
  'Hardy Nature', '- Nightmare', '- Protect', '',
].join('\n'));
fs.writeFileSync(path.join(out, 'smeargle-nightmare-splash-p2.txt'), [
  'Smeargle (M)', 'Ability: Own Tempo', 'Level: 100', 'EVs: 8 HP',
  'Hardy Nature', '- Splash', '',
].join('\n'));
fs.writeFileSync(path.join(out, 'smeargle-magikarp-switch-p2.txt'), [
  'Smeargle (M)', 'Ability: Own Tempo', 'Level: 100', 'EVs: 8 HP',
  'Hardy Nature', '- Splash', '', 'Magikarp (M)', 'Ability: Swift Swim',
  'Level: 100', 'EVs: 4 HP', 'Hardy Nature', '- Splash', '',
].join('\n'));
fs.writeFileSync(path.join(out, 'seviper-screech-p2.txt'), [
  'Seviper (M)', 'Ability: Shed Skin', 'Level: 100', 'EVs: 4 HP',
  'Hardy Nature', '- Screech', '',
].join('\n'));

function sleepingSmeargle(time) {
  const value = smeargle('slp');
  value.status_state.time = time;
  return value;
}

function writeCase({id, p2, p2Source, choices, seed = [1, 2, 3, 4],
  outcomes = [], extraFeatures = [], sourceFile = 'data/moves.ts; data/mods/gen3/moves.ts; sim/pokemon.ts'}) {
  const common = ['choice.move', 'handler.residual', 'state.canonical',
    'status.sleep', 'condition.volatile'];
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived', source_file: sourceFile,
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed,
    teams: [
      {source: 'gengar-nightmare-protect-p1.txt', normalized: [gengar]},
      {source: p2Source, normalized: p2},
    ],
    source_choices: choices, choices, forced_outcomes: outcomes,
    features: [...common, ...extraFeatures],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {
      max_boundaries: choices.length + 1,
      max_actions: choices.flat().filter(Boolean).length,
    },
  };
  fs.writeFileSync(path.join(out, `${id}.json`),
    `${JSON.stringify(value, null, 2)}\n`);
}

writeCase({
  id: 'nightmare-awake-rejection', p2: [smeargle(null)],
  p2Source: 'smeargle-nightmare-splash-p2.txt', choices: [['move 1', 'move 1']],
});
writeCase({
  id: 'nightmare-sleep-residual', p2: [sleepingSmeargle(5)],
  p2Source: 'smeargle-nightmare-splash-p2.txt', choices: [['move 1', 'move 1']],
});
writeCase({
  id: 'nightmare-wake-cleanup', p2: [sleepingSmeargle(1)],
  p2Source: 'smeargle-nightmare-splash-p2.txt', choices: [['move 1', 'move 1']],
});
writeCase({
  id: 'nightmare-switch-cleanup',
  p2: [sleepingSmeargle(5), magikarp],
  p2Source: 'smeargle-magikarp-switch-p2.txt',
  choices: [['move 1', 'move 1'], ['move 1', 'switch 2']],
  extraFeatures: ['choice.switch'],
});
writeCase({
  id: 'nightmare-shed-skin-order', p2: [seviper],
  p2Source: 'seviper-screech-p2.txt', choices: [['move 1', 'move 1']],
  seed: [1, 2, 3, 7],
  outcomes: [{
    label: 'ability.residual_status_cure', occurrence: 1,
    range: 100, result: 22,
  }],
  extraFeatures: ['prng.labeled'],
  sourceFile: 'data/moves.ts; data/mods/gen3/moves.ts; data/mods/gen4/abilities.ts; sim/pokemon.ts',
});
