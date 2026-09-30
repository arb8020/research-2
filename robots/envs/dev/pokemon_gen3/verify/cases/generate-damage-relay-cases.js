#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const names = new Map([
  ['smeargle', 'Smeargle'], ['blissey', 'Blissey'], ['gengar', 'Gengar'],
  ['owntempo', 'Own Tempo'], ['naturalcure', 'Natural Cure'],
  ['levitate', 'Levitate'], ['falseswipe', 'False Swipe'],
  ['splash', 'Splash'], ['protect', 'Protect'],
]);

const mon = (species, gender, ability, moves, stats, initialHp) => ({
  species, level: 100, gender, ability, item: '', moves, stats, status: null,
  ...(initialHp === undefined ? {} : {initial_hp: initialHp}),
});
const smeargle = (moves = ['falseswipe']) => mon(
  'smeargle', 'M', 'owntempo', moves, [251, 76, 106, 76, 126, 186]);
const blissey = (moves = ['splash'], hp) => mon(
  'blissey', 'F', 'naturalcure', moves, [651, 56, 56, 186, 306, 146], hp);
const gengar = () => mon(
  'gengar', 'M', 'levitate', ['splash'], [261, 166, 156, 296, 186, 256]);

function writeTeam(filename, team) {
  fs.writeFileSync(path.join(out, filename), team.map(pokemon => [
    `${names.get(pokemon.species)} (${pokemon.gender})`,
    `Ability: ${names.get(pokemon.ability)}`,
    'Level: 100', 'Hardy Nature',
    ...pokemon.moves.map(move => `- ${names.get(move)}`), '',
  ].join('\n')).join('\n'));
}

function emit(id, p1, p2, choices, forced = [], extra = [], seed = [1, 2, 3, 4]) {
  const left = `${id}-p1.txt`;
  const right = `${id}-p2.txt`;
  writeTeam(left, p1);
  writeTeam(right, p2);
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/moves.ts; sim/battle.ts; sim/battle-actions.ts',
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed,
    teams: [{source: left, normalized: p1}, {source: right, normalized: p2}],
    source_choices: choices, choices, forced_outcomes: forced,
    features: [
      'choice.move', 'damage.gen3', 'handler.damage', 'move.false-swipe',
      'prng.labeled', 'state.canonical', ...extra,
    ],
    boundaries: [
      'request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng',
      'terminal',
    ],
    limits: {
      max_boundaries: choices.length + 1,
      max_actions: choices.length * 2,
    },
  };
  fs.writeFileSync(
    path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

emit('damage-relay-false-swipe-nonlethal', [smeargle()], [blissey()],
  [['move 1', 'move 1']]);
emit('damage-relay-false-swipe-lethal-to-one', [smeargle()], [blissey(['splash'], 2)],
  [['move 1', 'move 1']]);
emit('damage-relay-false-swipe-zero-repeat', [smeargle()], [blissey(['splash'], 2)],
  [['move 1', 'move 1'], ['move 1', 'move 1']]);
emit('damage-relay-false-swipe-critical', [smeargle()], [blissey(['splash'], 2)],
  [['move 1', 'move 1']], [
    {label: 'move.critical', occurrence: 1, range: 16, result: 0},
    {label: 'move.damage_roll', occurrence: 1, range: 16, result: 8},
  ], ['damage.critical'], [1, 2, 3, 6]);
emit('damage-relay-false-swipe-protect', [smeargle()], [blissey(['protect'])],
  [['move 1', 'move 1']], [], ['hit.protect']);
emit('damage-relay-false-swipe-ghost-immunity', [smeargle()], [gengar()],
  [['move 1', 'move 1']], [], ['hit.type-immunity']);
