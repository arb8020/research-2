#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const id = 'recoil-trio-rotation';
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const p1 = `${id}-p1.txt`;
const p2 = `${id}-p2.txt`;
fs.writeFileSync(path.join(out, p1), [
  'Smeargle (M)', 'Ability: Own Tempo', 'Level: 100',
  'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe', 'Hardy Nature',
  '- Submission', '- Take Down', '- Volt Tackle', '',
].join('\n'));
fs.writeFileSync(path.join(out, p2), [
  'Blissey (F)', 'Ability: Natural Cure', 'Level: 100',
  'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe', 'Hardy Nature',
  '- Splash', '',
].join('\n'));
const choices = [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 3', 'move 1']];
const value = {
  schema: 'pokemon-native-differential-case-v1', id,
  provenance: {kind: 'showdown-derived', source_file: 'sim/battle-actions.ts',
    test_name: 'remaining declarative recoil descriptors use generic staging',
    oracle_revision: revision},
  format: 'gen3ou', seed: [1, 2, 3, 4],
  teams: [
    {source: p1, normalized: [{species: 'smeargle', level: 100, gender: 'M',
      ability: 'owntempo', item: '', moves: ['submission', 'takedown', 'volttackle'],
      stats: [251, 76, 106, 76, 126, 186], status: null}]},
    {source: p2, normalized: [{species: 'blissey', level: 100, gender: 'F',
      ability: 'naturalcure', item: '', moves: ['splash'],
      stats: [651, 56, 56, 186, 306, 146], status: null}]},
  ],
  source_choices: choices, choices, forced_outcomes: [],
  features: ['effect.recoil', 'hit.accuracy', 'prng.labeled', 'state.canonical'],
  boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
  limits: {max_boundaries: 4, max_actions: 6},
};
fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
