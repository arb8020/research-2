#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

function member(species, gender, ability, moves, stats) {
  return {species, level: 100, gender, ability, item: '', moves, stats, status: null};
}
function teamText(name, gender, ability, moves, evs = null) {
  return [`${name} (${gender})`, `Ability: ${ability}`, 'Level: 100',
    ...(evs ? [`EVs: ${evs}`] : []), 'Hardy Nature',
    ...moves.map(move => `- ${move}`), ''].join('\n');
}
function emit(id, left, right, choices, testName) {
  const leftSource = `${id}-p1.txt`;
  const rightSource = `${id}-p2.txt`;
  fs.writeFileSync(path.join(out, leftSource), left.text);
  fs.writeFileSync(path.join(out, rightSource), right.text);
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived', source_file: 'data/mods/gen5/moves.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [
      {source: leftSource, normalized: [left.member]},
      {source: rightSource, normalized: [right.member]},
    ],
    source_choices: choices, choices, forced_outcomes: [],
    features: ['choice.move', 'effect.boost', 'hit.always', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

const mixedLeftMoves = ['swordsdance', 'growl', 'psychup'];
const mixedRightMoves = ['agility', 'sandattack', 'splash'];
emit('psych-up-mixed-replacement', {
  text: teamText('Smeargle', 'M', 'Own Tempo', ['Swords Dance', 'Growl', 'Psych Up'],
    '1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe'),
  member: member('smeargle', 'M', 'owntempo', mixedLeftMoves,
    [251, 76, 106, 76, 126, 186]),
}, {
  text: teamText('Smeargle', 'F', 'Own Tempo', ['Agility', 'Sand-Attack', 'Splash'], '4 Spe'),
  member: member('smeargle', 'F', 'owntempo', mixedRightMoves,
    [251, 76, 106, 76, 126, 187]),
}, [
  ['move 1', 'move 1'], ['move 2', 'move 2'], ['move 3', 'move 3'],
], 'Psych Up atomically replaces all seven boost stages');

const bypassLeftMoves = ['splash', 'psychup'];
const bypassRightMoves = ['substitute', 'calmmind', 'protect'];
emit('psych-up-substitute-bypass', {
  text: teamText('Smeargle', 'M', 'Own Tempo', ['Splash', 'Psych Up'],
    '1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe'),
  member: member('smeargle', 'M', 'owntempo', bypassLeftMoves,
    [251, 76, 106, 76, 126, 186]),
}, {
  text: teamText('Dusclops', 'M', 'Pressure', ['Substitute', 'Calm Mind', 'Protect'],
    '1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe'),
  member: member('dusclops', 'M', 'pressure', bypassRightMoves,
    [221, 176, 296, 156, 296, 86]),
}, [
  ['move 1', 'move 1'], ['move 1', 'move 2'], ['move 2', 'move 3'],
], 'Psych Up bypasses Substitute without boost events');

const ghostLeftMoves = ['splash', 'psychup'];
const ghostRightMoves = ['calmmind', 'protect'];
emit('psych-up-protect-ghost', {
  text: teamText('Smeargle', 'M', 'Own Tempo', ['Splash', 'Psych Up'],
    '1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe'),
  member: member('smeargle', 'M', 'owntempo', ghostLeftMoves,
    [251, 76, 106, 76, 126, 186]),
}, {
  text: teamText('Dusclops', 'M', 'Pressure', ['Calm Mind', 'Protect'],
    '1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe'),
  member: member('dusclops', 'M', 'pressure', ghostRightMoves,
    [221, 176, 296, 156, 296, 86]),
}, [
  ['move 1', 'move 1'], ['move 2', 'move 2'],
], 'Psych Up bypasses Protect and Normal immunity against a Ghost target');
