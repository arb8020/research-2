#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const ninjask = (status = null, initialHP) => ({
  species: 'ninjask', level: 100, gender: 'M', nature: 'hardy',
  ability: 'speedboost', item: '', moves: ['swordsdance'],
  stats: [263, 216, 126, 136, 136, 356], status,
  ...(status === 'tox' ? {status_state: {kind: 'toxic', stage: 0}} : {}),
  ...(initialHP === undefined ? {} : {initial_hp: initialHP}),
});
const magikarp = {species: 'magikarp', level: 100, gender: 'M', nature: 'hardy',
  ability: 'swiftswim', item: '', moves: ['splash'],
  stats: [181, 56, 146, 66, 76, 196], status: null};
const blissey = {species: 'blissey', level: 100, gender: 'M', nature: 'hardy',
  ability: 'naturalcure', item: '', moves: ['softboiled'],
  stats: [651, 56, 56, 186, 306, 146], status: null};
const display = new Map([
  ['ninjask', 'Ninjask'], ['magikarp', 'Magikarp'], ['blissey', 'Blissey'],
  ['speedboost', 'Speed Boost'], ['swiftswim', 'Swift Swim'],
  ['naturalcure', 'Natural Cure'], ['softboiled', 'Soft-Boiled'],
  ['swordsdance', 'Swords Dance'], ['splash', 'Splash'],
]);
const teamText = team => team.map(mon => [
  `${display.get(mon.species)} (M)`, `Ability: ${display.get(mon.ability)}`,
  'Level: 100', 'EVs: 1 HP', 'Hardy Nature',
  ...mon.moves.map(move => `- ${display.get(move)}`), '',
].join('\n')).join('\n');
function emit(id, p1, p2, choices, testName) {
  const p1File = `${id}-p1.txt`;
  const p2File = `${id}-p2.txt`;
  fs.writeFileSync(path.join(out, p1File), teamText(p1));
  fs.writeFileSync(path.join(out, p2File), teamText(p2));
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/abilities.ts; data/mods/gen4/abilities.ts; sim/battle.ts; sim/battle-actions.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: p1File, normalized: p1}, {source: p2File, normalized: p2}],
    source_choices: choices, choices, forced_outcomes: [],
    features: ['choice.move', 'effect.boost', 'handler.residual',
      'handler.speed-boost', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1,
      max_actions: choices.flat().filter(Boolean).length},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}
emit('speed-boost-initial-active', [ninjask()], [blissey],
  [['move 1', 'move 1']], 'initial active boosts at its first residual');
emit('speed-boost-switch-delay', [magikarp, ninjask()], [blissey],
  [['switch 2', 'move 1'], ['move 1', 'move 1']],
  'same-turn switch-in waits until the following residual');
emit('speed-boost-before-toxic-ko', [ninjask('tox', 1), magikarp], [blissey],
  [['move 1', 'move 1'], ['switch 2', null]],
  'order 10 suborder 3 boost precedes Toxic suborder 6 and forced replacement');
emit('speed-boost-stage-cap', [ninjask()], [blissey],
  Array.from({length: 7}, () => ['move 1', 'move 1']),
  'repeated residual boosts clamp at the generation stage cap');
