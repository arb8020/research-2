#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const id = 'self-drop-connected-rotation';
const leftSource = `${id}-p1.txt`;
const rightSource = `${id}-p2.txt`;
fs.writeFileSync(path.join(out, leftSource), [
  'Smeargle (M)', 'Ability: Own Tempo', 'Level: 100',
  'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe', 'Hardy Nature',
  '- Overheat', '- Psycho Boost', '- Superpower', '',
].join('\n'));
fs.writeFileSync(path.join(out, rightSource), [
  'Blissey (F)', 'Ability: Natural Cure', 'Level: 100',
  'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe', 'Hardy Nature',
  '- Splash', '',
].join('\n'));

const choices = [
  ['move 1', 'move 1'], ['move 2', 'move 1'], ['move 3', 'move 1'],
];
const value = {
  schema: 'pokemon-native-differential-case-v1', id,
  provenance: {kind: 'showdown-derived', source_file: 'sim/battle-actions.ts',
    test_name: 'post-hit self boost drops are one move-owned product',
    oracle_revision: revision},
  format: 'gen3ou', seed: [1, 2, 3, 4],
  teams: [
    {source: leftSource, normalized: [{species: 'smeargle', level: 100,
      gender: 'M', ability: 'owntempo', item: '',
      moves: ['overheat', 'psychoboost', 'superpower'],
      stats: [251, 76, 106, 76, 126, 186], status: null}]},
    {source: rightSource, normalized: [{species: 'blissey', level: 100,
      gender: 'F', ability: 'naturalcure', item: '', moves: ['splash'],
      stats: [651, 56, 56, 186, 306, 146], status: null}]},
  ],
  source_choices: choices, choices,
  forced_outcomes: [],
  features: ['effect.boost', 'hit.accuracy', 'prng.labeled',
    'state.canonical'],
  boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
  limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
};
fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
