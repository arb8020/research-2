#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const sets = {
  gengar: {ability: 'Levitate', moves: ['Thunder Wave', 'Confuse Ray'], stats: [261, 166, 156, 296, 186, 256]},
  persian: {ability: 'Limber', moves: ['Water Pulse', 'Thunder Wave'], stats: [271, 176, 156, 166, 166, 266]},
  alakazam: {ability: 'Synchronize', moves: ['Splash'], stats: [251, 136, 126, 306, 206, 276]},
  machop: {ability: 'Guts', moves: ['Splash'], stats: [281, 196, 136, 106, 106, 106]},
  smeargle: {ability: 'Own Tempo', moves: ['Splash'], stats: [251, 76, 106, 76, 126, 186]},
  vaporeon: {ability: 'Water Absorb', moves: ['Ember', 'Splash'], stats: [401, 166, 156, 256, 226, 166]},
  magikarp: {ability: 'Swift Swim', moves: ['Splash'], stats: [181, 56, 146, 66, 76, 196]},
};

const id = text => text.toLowerCase().replace(/[^a-z0-9]+/g, '');
const title = text => text.replace(/(^|\s)\S/g, c => c.toUpperCase());
function member(species, item = false, moves = sets[species].moves) {
  const set = sets[species];
  return {
    export: `${title(species)} (M)${item ? ' @ Lum Berry' : ''}\nAbility: ${set.ability}\nLevel: 100\n` +
      'EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
      moves.map(move => `- ${move}`).join('\n') + '\n',
    normalized: {species, level: 100, gender: 'M', ability: id(set.ability),
      item: item ? 'lumberry' : '', moves: moves.map(id), stats: set.stats, status: null},
  };
}
function team(caseID, side, specs) {
  const source = `${caseID}-p${side + 1}.txt`;
  const built = specs.map(spec => member(...spec));
  fs.writeFileSync(path.join(out, source), built.map(entry => entry.export).join('\n'));
  return {source, normalized: built.map(entry => entry.normalized)};
}
function emit(caseID, p1, p2, choices, testName, seed = [601, 17, 31, 17], sourceChoices = choices) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {kind: 'showdown-derived', source_file: 'data/items.ts; data/moves.ts; sim/battle.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed, teams: [team(caseID, 0, p1), team(caseID, 1, p2)],
    source_choices: sourceChoices.map(pair => [...pair]), choices, forced_outcomes: [],
    features: ['choice.move', 'item.consumption', 'handler.status-update',
      'state.canonical', 'condition.nonvolatile-status', 'volatile.confusion'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('berry-lum-primary-status', [['gengar', false, ['Thunder Wave']]], [['machop', true]],
  [['move 1', 'move 1']], 'Lum immediately cures a primary major status');
emit('berry-lum-secondary-status', [['smeargle', false, ['Ember']]], [['machop', true]],
  [['move 1', 'move 1']], 'Lum immediately cures a damaging-secondary major status');
emit('berry-lum-status-then-confusion', [['persian', false, ['Water Pulse', 'Thunder Wave']]],
  [['machop', true, ['Splash']]], [['move 1', 'move 1'], ['move 2', 'move 1']],
  'Lum immediately cures confusion, then cannot consume again for a later status');
emit('berry-lum-confusion-update', [['gengar', false, ['Confuse Ray']]], [['machop', true]],
  [['move 1', 'move 1']], 'Lum cures confusion through Update');
emit('berry-lum-status-mismatch-no-double-eat', [['gengar', false, ['Thunder Wave']]], [['machop', true]],
  [['move 1', 'move 1'], ['move 1', 'move 1']], 'Consumed Lum cannot eat twice after curing status');
emit('berry-lum-own-tempo', [['gengar', false, ['Confuse Ray']]], [['smeargle', true]],
  [['move 1', 'move 1']], 'Own Tempo prevents confusion before Lum can consume');
emit('berry-lum-status-prevention', [['gengar', false, ['Thunder Wave']]], [['persian', true, ['Splash']]],
  [['move 1', 'move 1']], 'Status immunity prevents status before Lum can consume');
emit('berry-lum-switch-persistence', [['machop', true], ['vaporeon', false, ['Splash']]], [['magikarp', false]],
  [['switch 2', 'move 1'], ['switch 1', 'move 1']], 'Held Lum persists across switching without a cure',
  [601, 17, 31, 17], [['switch 2', 'move 1'], ['switch 2', 'move 1']]);

console.log('generated 8 Lum Berry cases');
