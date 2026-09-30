#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const display = new Map([
  ['persian', 'Persian'], ['alakazam', 'Alakazam'], ['milotic', 'Milotic'],
  ['blissey', 'Blissey'], ['limber', 'Limber'], ['synchronize', 'Synchronize'],
  ['marvelscale', 'Marvel Scale'], ['naturalcure', 'Natural Cure'],
  ['scratch', 'Scratch'], ['psychic', 'Psychic'], ['surf', 'Surf'],
  ['softboiled', 'Soft-Boiled'],
]);
const mon = (species, gender, ability, moves, stats, status = null) => ({
  species, level: 100, gender, ability, item: '', moves, stats, status,
});
const persian = () => mon(
  'persian', 'M', 'limber', ['scratch'], [271, 176, 156, 166, 166, 266]);
const alakazam = () => mon(
  'alakazam', 'M', 'synchronize', ['psychic'], [251, 136, 126, 306, 206, 276]);
const milotic = status => mon(
  'milotic', 'F', 'marvelscale', ['surf'], [331, 156, 194, 236, 286, 198], status);
const blissey = () => mon(
  'blissey', 'F', 'naturalcure', ['softboiled'], [651, 56, 56, 186, 306, 146]);

function writeTeam(filename, pokemon) {
  const text = pokemon.map(p => [
    `${display.get(p.species)} (${p.gender})`,
    `Ability: ${display.get(p.ability)}`,
    'Level: 100', 'Hardy Nature',
    ...p.moves.map(move => `- ${display.get(move)}`), '',
  ].join('\n')).join('\n');
  fs.writeFileSync(path.join(out, filename), text);
}

function emit(id, p1, p2, choices, forced_outcomes = [], seed = [1, 2, 3, 4],
  source_choices = choices) {
  const left = `${id}-p1.txt`, right = `${id}-p2.txt`;
  writeTeam(left, p1); writeTeam(right, p2);
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/abilities.ts; sim/battle-actions.ts',
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed,
    teams: [{source: left, normalized: p1}, {source: right, normalized: p2}],
    source_choices, choices, forced_outcomes,
    features: [
      'choice.move', 'handler.modify-defense', 'handler.marvel-scale',
      'damage.gen3', 'damage.critical', 'condition.nonvolatile-status',
      'prng.labeled', 'queue.speed', 'state.canonical',
    ],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

emit('marvel-scale-physical-control', [persian()], [milotic(null)],
  [['move 1', 'move 1']]);
emit('marvel-scale-physical-paralyzed', [persian()], [milotic('par')],
  [['move 1', 'move 1']]);
emit('marvel-scale-special-paralyzed', [alakazam()], [milotic('par')],
  [['move 1', 'move 1']]);
emit('marvel-scale-critical-paralyzed', [persian()], [milotic('par')],
  [['move 1', 'move 1']], [
    {label: 'move.critical', occurrence: 1, range: 16, result: 0},
    {label: 'move.damage_roll', occurrence: 1, range: 16, result: 8},
  ], [1, 2, 3, 6]);
emit('marvel-scale-switch-persistence', [persian()], [milotic('par'), blissey()],
  [['move 1', 'switch 2'], ['move 1', 'switch 1']], [], [1, 2, 3, 4],
  [['move 1', 'switch 2'], ['move 1', 'switch 2']]);
