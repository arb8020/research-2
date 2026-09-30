#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const catalog = {
  smeargle: {name: 'Smeargle', gender: 'M', ability: 'Own Tempo',
    stats: [251, 76, 106, 76, 126, 186]},
  blissey: {name: 'Blissey', gender: 'F', ability: 'Natural Cure',
    stats: [651, 56, 56, 186, 306, 146]},
  salamence: {name: 'Salamence', gender: 'M', ability: 'Intimidate',
    stats: [331, 306, 196, 256, 196, 236]},
  gyarados: {name: 'Gyarados', gender: 'M', ability: 'Intimidate',
    stats: [331, 286, 194, 156, 236, 198]},
  starmie: {name: 'Starmie', gender: 'N', ability: 'Natural Cure',
    stats: [261, 186, 206, 236, 206, 266]},
  magikarp: {name: 'Magikarp', gender: 'M', ability: 'Swift Swim',
    stats: [181, 56, 146, 66, 76, 196]},
};
const moveNames = {splash: 'Splash', howl: 'Howl', overheat: 'Overheat'};
const abilityIDs = {smeargle: 'owntempo', blissey: 'naturalcure',
  salamence: 'intimidate', gyarados: 'intimidate', starmie: 'naturalcure',
  magikarp: 'swiftswim'};

function member(species, moves, item = '', status = null) {
  const p = catalog[species];
  const gender = p.gender === 'N' ? '' : ` (${p.gender})`;
  return {
    export: `${p.name}${gender}${item ? ' @ White Herb' : ''}\n` +
      `Ability: ${p.ability}\nLevel: 100\nEVs: 1 HP\nSerious Nature\n` +
      moves.map(move => `- ${moveNames[move]}`).join('\n') + '\n',
    normalized: {species, level: 100, gender: p.gender, nature: 'serious',
      ability: abilityIDs[species], item, moves, stats: p.stats, status},
  };
}

function team(caseID, side, entries) {
  const source = `${caseID}-p${side + 1}.txt`;
  fs.writeFileSync(path.join(out, source),
    entries.map(entry => entry.export).join('\n'));
  return {source, normalized: entries.map(entry => entry.normalized)};
}

function emit(caseID, p1, p2, choices, testName, forcedOutcomes = [], extra = [],
  seed = [743, 31, 47, 89]) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/items.ts; data/mods/gen4/scripts.ts; sim/battle-actions.ts; sim/battle.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed,
    teams: [team(caseID, 0, p1), team(caseID, 1, p2)],
    source_choices: choices.map(pair => [...pair]), choices,
    forced_outcomes: forcedOutcomes,
    features: ['item.consumption', 'effect.boost', 'state.canonical', ...extra],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`),
    `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('item-white-herb-after-move',
  [member('smeargle', ['howl', 'overheat'], 'whiteherb')],
  [member('blissey', ['splash'])],
  [['move 1', 'move 1'], ['move 2', 'move 1']],
  'AfterMove consumes White Herb, clears the Overheat drop, and preserves a positive Attack stage',
  [{label: 'move.accuracy', occurrence: 1, range: 100, result: 28},
    {label: 'move.critical', occurrence: 1, range: 16, result: 4},
    {label: 'move.damage_roll', occurrence: 1, range: 16, result: 3},
    {label: 'move.secondary', occurrence: 1, range: 100, result: 67}],
  ['hit.accuracy', 'prng.labeled']);

emit('item-white-herb-miss-control',
  [member('smeargle', ['overheat'], 'whiteherb')],
  [member('blissey', ['splash'])], [['move 1', 'move 1']],
  'AfterMove runs after an Overheat miss but White Herb remains because no drop occurred',
  [{label: 'move.accuracy', occurrence: 1, range: 100, result: 90}],
  ['hit.accuracy', 'prng.labeled'], [743, 31, 47, 1]);

emit('item-white-herb-start-consumes',
  [member('salamence', ['splash'])],
  [member('blissey', ['splash'], 'whiteherb')], [],
  'A faster opposing Intimidate runs before the slower holder item Start, which consumes White Herb',
  [], ['ability.intimidate', 'queue.speed']);

emit('item-white-herb-start-order-control',
  [member('starmie', ['splash'], 'whiteherb')],
  [member('gyarados', ['splash'])], [],
  'A faster holder item Start precedes slower opposing Intimidate, leaving the negative stage and item',
  [], ['ability.intimidate', 'queue.speed']);

emit('item-white-herb-any-switch-in',
  [member('starmie', ['splash'], 'whiteherb')],
  [member('gyarados', ['splash']), member('magikarp', ['splash'])],
  [['move 1', 'switch 2']],
  'An existing negative stage is cleared by White Herb on another Pokemon switching in',
  [], ['ability.intimidate', 'choice.switch', 'queue.speed']);

emit('item-white-herb-residual',
  [member('starmie', ['splash'], 'whiteherb', 'par')],
  [member('gyarados', ['splash'], '', 'par')],
  [['move 1', 'move 1']],
  'Both selected moves are stopped by paralysis, leaving Residual as the first White Herb trigger after Intimidate',
  [{label: 'status.paralysis.before_move', occurrence: 1, range: 4, result: 0},
    {label: 'status.paralysis.before_move', occurrence: 2, range: 4, result: 0}],
  ['ability.intimidate', 'handler.residual', 'status.paralysis', 'prng.labeled'],
  [8, 31, 47, 89]);

console.log('generated 6 White Herb cases');
