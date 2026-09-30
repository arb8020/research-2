#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const sets = {
  gengar: {ability: 'Levitate', moves: ['Confuse Ray', 'Thunder Wave'],
    stats: [261, 166, 156, 296, 186, 256]},
  machop: {ability: 'Guts', moves: ['Splash'], stats: [281, 196, 136, 106, 106, 106]},
  persian: {ability: 'Limber', moves: ['Water Pulse', 'Splash'],
    stats: [271, 176, 156, 166, 166, 266]},
  alakazam: {ability: 'Synchronize', moves: ['Splash'], stats: [251, 136, 126, 306, 206, 276]},
  smeargle: {ability: 'Own Tempo', moves: ['Splash', 'Substitute'],
    stats: [251, 76, 106, 76, 126, 186]},
  vaporeon: {ability: 'Water Absorb', moves: ['Splash'], stats: [401, 166, 156, 256, 226, 166]},
  magikarp: {ability: 'Swift Swim', moves: ['Splash'], stats: [181, 56, 146, 66, 76, 196]},
};

const id = text => text.toLowerCase().replace(/[^a-z0-9]+/g, '');
function member(species, item = '', moves = sets[species].moves) {
  const set = sets[species];
  const title = species[0].toUpperCase() + species.slice(1);
  return {
    export: `${title} (M)${item ? ` @ Persim Berry` : ''}\nAbility: ${set.ability}\nLevel: 100\n` +
      `EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
      moves.map(move => `- ${move}`).join('\n') + '\n',
    normalized: {species, level: 100, gender: 'M', ability: id(set.ability),
      item: item ? 'persimberry' : '', moves: moves.map(id), stats: set.stats, status: null},
  };
}
function team(caseID, side, specs) {
  const source = `${caseID}-p${side + 1}.txt`;
  const built = specs.map(spec => member(...spec));
  fs.writeFileSync(path.join(out, source), built.map(entry => entry.export).join('\n'));
  return {source, normalized: built.map(entry => entry.normalized)};
}
function emit(caseID, p1, p2, choices, testName, seed = [601, 17, 31, 17],
  sourceChoices = choices) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {kind: 'showdown-derived', source_file: 'data/items.ts; data/moves.ts; sim/battle.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed, teams: [team(caseID, 0, p1), team(caseID, 1, p2)],
    source_choices: sourceChoices.map(pair => [...pair]), choices, forced_outcomes: [],
    features: ['choice.move', 'item.consumption', 'handler.status-update',
      'state.canonical', 'volatile.confusion'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('berry-persim-primary-update', [['gengar', '', ['Confuse Ray']]], [['machop', 'persim']],
  [['move 1', 'move 1']], 'Persim cures primary confusion in the inflicting move post-move Update');
emit('berry-persim-secondary-delayed-update', [['persian', '', ['Water Pulse']]], [['alakazam', 'persim']],
  [['move 1', 'move 1']],
  'Persim leaves a damaging secondary until the next genuine Update');
emit('berry-persim-status-mismatch', [['gengar', '', ['Thunder Wave']]], [['machop', 'persim']],
  [['move 1', 'move 1']], 'Persim does not consume for a mismatched major status');
emit('berry-persim-switch-persistence', [['machop', 'persim'], ['vaporeon']], [['magikarp']],
  [['switch 2', 'move 1'], ['switch 1', 'move 1']],
  'Held Persim persists across switching without confusion', [601, 17, 31, 17],
  [['switch 2', 'move 1'], ['switch 2', 'move 1']]);
emit('berry-persim-own-tempo', [['gengar', '', ['Confuse Ray']]], [['smeargle', 'persim', ['Splash']]],
  [['move 1', 'move 1']], 'Own Tempo rejects confusion before Persim can consume');
emit('berry-persim-substitute', [['gengar', '', ['Confuse Ray']]], [['persian', 'persim', ['Substitute']]],
  [['move 1', 'move 1']], 'Substitute blocks confusion before Persim can consume');

console.log('generated 6 Persim Berry cases');
