#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const sets = {
  persian: {gender: 'M', ability: 'Limber', stats: [271, 176, 156, 166, 166, 266]},
  blissey: {gender: 'F', ability: 'Natural Cure', stats: [651, 56, 56, 186, 306, 146]},
  gengar: {gender: 'M', ability: 'Levitate', stats: [261, 166, 156, 296, 186, 256]},
  skarmory: {gender: 'M', ability: 'Keen Eye', stats: [271, 196, 316, 116, 176, 176]},
  magikarp: {gender: 'M', ability: 'Swift Swim', stats: [181, 56, 146, 66, 76, 196]},
};
const id = value => value.toLowerCase().replace(/[^a-z0-9]+/g, '');

function member(species, moves, initialHP) {
  const set = sets[species];
  const name = species[0].toUpperCase() + species.slice(1);
  return {
    export: `${name} (${set.gender})\nAbility: ${set.ability}\nLevel: 100\n` +
      `EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
      `${moves.map(move => `- ${move}`).join('\n')}\n`,
    normalized: {species, level: 100, gender: set.gender, nature: 'hardy',
      ability: id(set.ability), item: '', moves: moves.map(id), stats: set.stats,
      status: null, ...(initialHP === undefined ? {} : {initial_hp: initialHP})},
  };
}

function team(caseID, side, specs) {
  const source = `${caseID}-p${side + 1}.txt`;
  const built = specs.map(spec => member(...spec));
  fs.writeFileSync(path.join(out, source), built.map(value => value.export).join('\n'));
  return {source, normalized: built.map(value => value.normalized)};
}

function emit(caseID, p1, p2, choices, testName, forcedOutcomes = []) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/conditions.ts; data/mods/gen4/conditions.ts; sim/pokemon.ts; sim/battle-actions.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [forcedOutcomes[0]?.result === 0 ? 702 : 701, 29, 43, 83],
    teams: [team(caseID, 0, p1), team(caseID, 1, p2)],
    source_choices: choices.map(pair => [...pair]), choices,
    forced_outcomes: forcedOutcomes,
    features: ['choice.move', 'request.legal-choices', 'queue.speed',
      'condition.volatile', 'lifecycle.condition-duration',
      'state.canonical', 'prng.labeled'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

const lock = result => [{label: 'condition.lockedmove.duration', occurrence: 1,
  range: 2, result}];
emit('locked-outrage-duration2', [['persian', ['Outrage']]], [['blissey', ['Splash']]],
  [['move 1', 'move 1'], ['move 1', 'move 1']], 'Outrage two-use lock and fatigue confusion', lock(0));
emit('locked-outrage-duration3', [['persian', ['Outrage']]], [['blissey', ['Splash']]],
  [['move 1', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 1']],
  'Outrage three-use restart and one-PP retention', lock(1));
emit('locked-petal-dance-duration2', [['persian', ['Petal Dance']]], [['blissey', ['Splash']]],
  [['move 1', 'move 1'], ['move 1', 'move 1']], 'Petal Dance shares lockedmove policy', lock(0));
emit('locked-thrash-duration2', [['persian', ['Thrash']]], [['skarmory', ['Splash']]],
  [['move 1', 'move 1'], ['move 1', 'move 1']], 'Thrash shares lockedmove policy', lock(0));
emit('locked-thrash-immunity', [['persian', ['Thrash']]], [['gengar', ['Splash']]],
  [['move 1', 'move 1']], 'Type immunity prevents initial lock');
emit('locked-outrage-protect', [['persian', ['Outrage']]], [['blissey', ['Protect']]],
  [['move 1', 'move 1']], 'Protect prevents initial lock');
emit('locked-outrage-ko-replacement', [['persian', ['Outrage']]],
  [['magikarp', ['Splash'], 1], ['blissey', ['Splash']]],
  [['move 1', 'move 1'], [null, 'switch 2']],
  'Lock persists while the opposing side makes a forced replacement', lock(1));
emit('locked-outrage-opponent-switch', [['persian', ['Outrage']]],
  [['blissey', ['Splash']], ['magikarp', ['Splash']]],
  [['move 1', 'move 1'], ['move 1', 'switch 2'], ['move 1', 'move 1']],
  'Selected move persists while the target voluntarily switches', lock(1));

console.log('generated 8 locked-move cases');
