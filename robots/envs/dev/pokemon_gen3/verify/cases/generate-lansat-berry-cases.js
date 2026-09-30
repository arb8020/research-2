#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

function member(item, move, initialHP) {
  return {
    export: `Smeargle (M)${item ? ' @ Lansat Berry' : ''}\n` +
      `Ability: Own Tempo\nLevel: 100\n` +
      `EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
      `Hardy Nature\n- ${move}\n`,
    normalized: {
      species: 'smeargle', level: 100, gender: 'M', nature: 'hardy',
      ability: 'owntempo', item, moves: [move.toLowerCase().replace(/ /g, '')],
      stats: [251, 76, 106, 76, 126, 186], status: null,
      ...(initialHP === undefined ? {} : {initial_hp: initialHP}),
    },
  };
}

function team(caseID, side, entry) {
  const source = `${caseID}-p${side + 1}.txt`;
  fs.writeFileSync(path.join(out, source), entry.export);
  return {source, normalized: [entry.normalized]};
}

function emit(caseID, initialHP, move, testName) {
  const p1 = member('lansatberry', move, initialHP);
  const p2 = member('', 'Splash');
  const choices = [['move 1', 'move 1']];
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/items.ts; data/mods/gen3/items.ts; sim/pokemon.ts',
      test_name: testName, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [619, 23, 41, 79],
    teams: [team(caseID, 0, p1), team(caseID, 1, p2)],
    source_choices: choices, choices, forced_outcomes: [],
    features: ['choice.move', 'handler.residual', 'item.consumption',
      'state.canonical', 'volatile.focus-energy'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`),
    `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('berry-lansat-threshold', 62, 'Splash',
  'Lansat Berry consumes at floor(max HP / 4) and installs Focus Energy');
emit('berry-lansat-above-threshold', 63, 'Splash',
  'Lansat Berry remains held immediately above its quarter-HP threshold');
emit('berry-lansat-focus-energy-duplicate', 62, 'Focus Energy',
  'Lansat Berry consumes while duplicate Focus Energy installation is a no-op');

console.log('generated 3 Lansat Berry cases');
