#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const names = new Map([
  ['smeargle', 'Smeargle'], ['blissey', 'Blissey'],
  ['owntempo', 'Own Tempo'], ['naturalcure', 'Natural Cure'],
  ['bounce', 'Bounce'], ['dig', 'Dig'], ['dive', 'Dive'],
  ['razorwind', 'Razor Wind'], ['skullbash', 'Skull Bash'],
  ['skyattack', 'Sky Attack'], ['splash', 'Splash'],
]);
const mon = (species, gender, ability, moves, stats) => ({
  species, level: 100, gender, ability, item: '', moves, stats, status: null,
});
const smeargle = move => mon(
  'smeargle', 'M', 'owntempo', [move], [251, 76, 106, 76, 126, 186]);
const blissey = () => mon(
  'blissey', 'F', 'naturalcure', ['splash'], [651, 56, 56, 186, 306, 146]);

function writeTeam(filename, team) {
  fs.writeFileSync(path.join(out, filename), team.map(pokemon => [
    `${names.get(pokemon.species)} (${pokemon.gender})`,
    `Ability: ${names.get(pokemon.ability)}`,
    'Level: 100', 'Hardy Nature',
    ...pokemon.moves.map(move => `- ${names.get(move)}`), '',
  ].join('\n')).join('\n'));
}

function emit(move) {
  const id = `two-turn-${move}-release`;
  const p1 = [smeargle(move)];
  const p2 = [blissey()];
  const left = `${id}-p1.txt`;
  const right = `${id}-p2.txt`;
  writeTeam(left, p1);
  writeTeam(right, p2);
  const choices = [['move 1', 'move 1'], ['move 1', 'move 1']];
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/conditions.ts; sim/battle-actions.ts',
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: left, normalized: p1}, {source: right, normalized: p2}],
    source_choices: choices, choices, forced_outcomes: [],
    features: [
      'choice.move', 'condition.volatile', 'damage.gen3', 'hit.accuracy',
      'prng.labeled', 'queue.speed', 'state.canonical',
    ],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 3, max_actions: 4},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

for (const move of [
  'bounce', 'dig', 'dive', 'razorwind', 'skullbash', 'skyattack',
]) emit(move);
