#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.join(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const stats = {
  smeargle: [251, 76, 106, 76, 126, 186],
  persian: [271, 176, 156, 166, 166, 266],
  gengar: [261, 166, 156, 296, 186, 256],
  dustox: [261, 136, 176, 136, 216, 166],
  alakazam: [251, 136, 126, 306, 206, 276],
  vaporeon: [401, 166, 156, 256, 226, 166],
};
const ability = {smeargle: 'owntempo', persian: 'limber', gengar: 'levitate', dustox: 'shielddust',
  alakazam: 'synchronize'};
ability.vaporeon = 'waterabsorb';

function title(id) {
  return ({dizzypunch: 'Dizzy Punch', dynamicpunch: 'Dynamic Punch',
    signalbeam: 'Signal Beam', psybeam: 'Psybeam', waterpulse: 'Water Pulse',
    owntempo: 'Own Tempo', shielddust: 'Shield Dust'})[id] ||
    id[0].toUpperCase() + id.slice(1);
}
function member(species, move, overrideAbility) {
  const a = overrideAbility || ability[species];
  return `${species[0].toUpperCase()}${species.slice(1)} (M)\nAbility: ${title(a)}\nLevel: 100\n` +
    `EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n- ${title(move)}\n`;
}
function normalized(species, move, overrideAbility) {
  return {species, level: 100, gender: 'M', ability: overrideAbility || ability[species],
    item: '', moves: [move], stats: stats[species], status: null};
}
function writeTeam(name, species, move, overrideAbility) {
  const file = `${name}.txt`;
  fs.writeFileSync(path.join(out, file), member(species, move, overrideAbility));
  return {source: file, normalized: [normalized(species, move, overrideAbility)]};
}
function emit(name, move, target, seed, choices = [['move 1', 'move 1']], extra = {}) {
  const source = extra.source || 'smeargle';
  const p1 = writeTeam(`${name}-p1`, source, move);
  const targetMove = extra.targetMove || 'splash';
  const p2 = writeTeam(`${name}-p2`, target, targetMove, extra.targetAbility);
  const value = {
    schema: 'pokemon-native-differential-case-v1', id: name,
    provenance: {kind: 'showdown-derived', source_file: 'data/moves.ts; sim/battle-actions.ts; sim/battle.ts',
      test_name: `Damaging confusion secondary: ${name}`, oracle_revision: revision},
    format: 'gen3ou', seed, teams: [p1, p2], source_choices: choices, choices,
    forced_outcomes: [],
    features: ['choice.move', 'damage.gen3', 'effect.secondary', 'hit.accuracy',
      'prng.labeled', 'prng.secondary', 'state.canonical', 'volatile.confusion'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${name}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

const success = [
  ['confusion', 'alakazam'], ['dizzypunch', 'smeargle'], ['dynamicpunch', 'alakazam'],
  ['psybeam', 'alakazam'], ['signalbeam', 'smeargle'], ['waterpulse', 'vaporeon'],
];
for (const [move, source] of success) emit(`confusion-secondary-${move}-success`, move, 'persian',
  [601, 17, 31, move === 'dynamicpunch' ? 20 : 17], undefined, {source});
emit('confusion-secondary-chance-failure', 'confusion', 'persian', [602, 17, 31, 1], undefined, {source: 'alakazam'});
emit('confusion-secondary-dynamic-punch-miss', 'dynamicpunch', 'persian', [601, 17, 31, 17], undefined, {source: 'alakazam'});
emit('confusion-secondary-immunity', 'dynamicpunch', 'gengar', [604, 17, 31, 1], undefined, {source: 'alakazam'});
emit('confusion-secondary-protect', 'waterpulse', 'persian', [605, 17, 31, 1], [['move 1', 'move 1']], {targetMove: 'protect', source: 'vaporeon'});
emit('confusion-secondary-substitute', 'psybeam', 'persian', [606, 17, 31, 1],
  [['move 1', 'move 1']], {targetMove: 'substitute', source: 'alakazam'});
emit('confusion-secondary-own-tempo', 'waterpulse', 'smeargle', [601, 17, 31, 17], undefined, {source: 'persian'});
emit('confusion-secondary-shield-dust', 'signalbeam', 'dustox', [601, 17, 31, 17]);

console.log('generated 13 confusion-secondary cases');
