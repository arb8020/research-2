#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
function member(species, gender, ability, moves, stats) {
  return {species, level: 100, gender, ability, item: '', moves, stats, status: null};
}
function text(species, gender, ability, moves, evs) {
  return [gender === 'N' ? species : `${species} (${gender})`, `Ability: ${ability}`, 'Level: 100',
    `EVs: ${evs}`, 'Hardy Nature', ...moves.map(x => `- ${x}`), ''].join('\n');
}
function emit(id, left, right, choices, features) {
  const p1 = `${id}-p1.txt`, p2 = `${id}-p2.txt`;
  fs.writeFileSync(path.join(out, p1), left.text);
  fs.writeFileSync(path.join(out, p2), right.text);
  const value = {schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/mods/gen3/moves.ts; sim/battle-actions.ts',
      test_name: `Haze HitField: ${id}`, oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: p1, normalized: [left.member]},
      {source: p2, normalized: [right.member]}],
    source_choices: choices, choices, forced_outcomes: [], features,
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2}};
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}
const zero = '1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe';
emit('haze-both-products', {
  text: text('Smeargle', 'M', 'Own Tempo', ['Swords Dance', 'Haze'], zero),
  member: member('smeargle', 'M', 'owntempo', ['swordsdance', 'haze'], [251,76,106,76,126,186]),
}, {
  text: text('Smeargle', 'F', 'Own Tempo', ['Calm Mind', 'Sand-Attack'], '4 Spe'),
  member: member('smeargle', 'F', 'owntempo', ['calmmind', 'sandattack'], [251,76,106,76,126,187]),
}, [['move 1','move 1'], ['move 2','move 2']],
['choice.move','effect.boost','hit.always','state.canonical']);
emit('haze-substitute-bypass', {
  text: text('Smeargle', 'M', 'Own Tempo', ['Splash', 'Haze'], zero),
  member: member('smeargle', 'M', 'owntempo', ['splash', 'haze'], [251,76,106,76,126,186]),
}, {
  text: text('Dusclops', 'M', 'Pressure', ['Substitute', 'Calm Mind', 'Protect'], zero),
  member: member('dusclops', 'M', 'pressure', ['substitute','calmmind','protect'], [221,176,296,156,296,86]),
}, [['move 1','move 1'], ['move 1','move 2'], ['move 2','move 3']],
['choice.move','effect.boost','hit.always','volatile.substitute','hit.substitute','hit.protect','ability.pressure','handler.deduct-pp','prng.labeled','state.canonical']);
emit('haze-pressure-staging', {
  text: text('Smeargle', 'M', 'Own Tempo', ['Haze'], zero),
  member: member('smeargle', 'M', 'owntempo', ['haze'], [251,76,106,76,126,186]),
}, {
  text: text('Articuno', 'N', 'Pressure', ['Agility'], zero),
  member: member('articuno', 'N', 'pressure', ['agility'], [321,206,236,226,286,206]),
}, [['move 1','move 1']],
['choice.move','effect.boost','hit.always','ability.pressure','handler.deduct-pp','prng.labeled','state.canonical']);
emit('haze-neutral-product', {
  text: text('Smeargle', 'M', 'Own Tempo', ['Haze'], zero),
  member: member('smeargle', 'M', 'owntempo', ['haze'], [251,76,106,76,126,186]),
}, {
  text: text('Smeargle', 'F', 'Own Tempo', ['Splash'], '4 Spe'),
  member: member('smeargle', 'F', 'owntempo', ['splash'], [251,76,106,76,126,187]),
}, [['move 1','move 1']],
['choice.move','effect.boost','hit.always','state.canonical']);
