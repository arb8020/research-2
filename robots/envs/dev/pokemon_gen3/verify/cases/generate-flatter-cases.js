#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.join(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const sets = {
  smeargle: {species: 'smeargle', level: 100, gender: 'M', ability: 'owntempo',
    stats: [251, 76, 106, 76, 126, 186]},
  persian: {species: 'persian', level: 100, gender: 'M', ability: 'limber',
    stats: [271, 176, 156, 166, 166, 266]},
  alakazam: {species: 'alakazam', level: 100, gender: 'M', ability: 'synchronize',
    stats: [251, 136, 126, 306, 206, 276]},
  metagross: {species: 'metagross', level: 90, gender: 'N', ability: 'clearbody',
    stats: [271, 275, 266, 203, 194, 158]},
};

function title(id) {
  return ({owntempo: 'Own Tempo', clearbody: 'Clear Body'})[id] ||
    id[0].toUpperCase() + id.slice(1);
}

function team(caseId, side, species, moves) {
  const set = sets[species];
  const filename = `${caseId}-${side}.txt`;
  const gender = set.gender === 'N' ? '' : ` (${set.gender})`;
  const text = `${title(species)}${gender}\nAbility: ${title(set.ability)}\nLevel: ${set.level}\n` +
    'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
    moves.map(move => `- ${title(move)}`).join('\n') + '\n';
  fs.writeFileSync(path.join(out, filename), text);
  return {source: filename, normalized: [{...set, item: '', moves, status: null}]};
}

function emit(config) {
  const value = {
    schema: 'pokemon-native-differential-case-v1', id: config.id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/abilities.ts; sim/battle.ts; sim/battle-actions.ts',
      test_name: config.testName, oracle_revision: revision},
    format: 'gen3ou', seed: config.seed || [731, 43, 19, 7],
    teams: [team(config.id, 'p1', config.p1.species, config.p1.moves),
      team(config.id, 'p2', config.p2.species, config.p2.moves)],
    source_choices: config.choices, choices: config.choices,
    forced_outcomes: config.forced || [],
    features: ['choice.move', 'effect.boost', 'handler.try-boost', 'hit.accuracy',
      'prng.labeled', 'state.canonical', 'volatile.confusion'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: config.choices.length + 1,
      max_actions: config.choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${config.id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

emit({id: 'flatter-success-order-duration',
  testName: 'Flatter applies Special Attack before confusion and stages its duration',
  p1: {species: 'smeargle', moves: ['flatter', 'splash']},
  p2: {species: 'metagross', moves: ['splash']},
  choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
  forced: [
    {label: 'move.accuracy', occurrence: 1, range: 100, result: 7},
    {label: 'condition.confusion.duration', occurrence: 1, range: 4, result: 0},
    {label: 'condition.confusion.action', occurrence: 1, range: 2, result: 1},
    {label: 'move.damage_roll', occurrence: 1, range: 16, result: 12},
  ]});

emit({id: 'flatter-own-tempo-partial-success',
  testName: 'Own Tempo prevents confusion without rolling back the positive target boost',
  p1: {species: 'persian', moves: ['flatter']},
  p2: {species: 'smeargle', moves: ['splash']}, choices: [['move 1', 'move 1']],
  forced: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 7}]});

emit({id: 'flatter-substitute-block',
  testName: 'Substitute blocks the complete Flatter primary effect product',
  p1: {species: 'smeargle', moves: ['flatter']},
  p2: {species: 'persian', moves: ['substitute']}, choices: [['move 1', 'move 1']],
  forced: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 7}]});

emit({id: 'flatter-protect-block',
  testName: 'Protect blocks the complete Flatter primary effect product',
  p1: {species: 'smeargle', moves: ['flatter']},
  p2: {species: 'persian', moves: ['protect']}, choices: [['move 1', 'move 1']],
  forced: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 7}]});

const capChoices = Array.from({length: 7}, () => ['move 1', 'move 1']);
emit({id: 'flatter-boost-cap',
  testName: 'Repeated Flatter clamps its positive target boost at plus six',
  p1: {species: 'persian', moves: ['flatter']},
  p2: {species: 'smeargle', moves: ['splash']}, choices: capChoices,
  forced: [7, 66, 93, 39, 50, 9, 49].map((result, index) =>
    ({label: 'move.accuracy', occurrence: index + 1, range: 100, result}))});

emit({id: 'flatter-clear-body-positive',
  testName: 'Clear Body TryBoost permits Flatter positive target boost',
  p1: {species: 'smeargle', moves: ['flatter']},
  p2: {species: 'metagross', moves: ['splash']}, choices: [['move 1', 'move 1']],
  forced: [
    {label: 'move.accuracy', occurrence: 1, range: 100, result: 7},
    {label: 'condition.confusion.duration', occurrence: 1, range: 4, result: 0},
  ]});

console.log('generated 6 Flatter cases');
