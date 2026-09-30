#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

function member(item, initialHP) {
  return {
    export: `Smeargle (M)${item ? ' @ Starf Berry' : ''}\n` +
      `Ability: Own Tempo\nLevel: 100\n` +
      `EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
      `Hardy Nature\n- Splash\n`,
    normalized: {
      species: 'smeargle', level: 100, gender: 'M', nature: 'hardy',
      ability: 'owntempo', item, moves: ['splash'],
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

function emit(caseID, initialHP, seed, testName, selectedStat) {
  const choices = [['move 1', 'move 1']];
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/items.ts; data/mods/gen3/items.ts; sim/pokemon.ts; sim/prng.ts',
      test_name: testName, oracle_revision: revision,
    },
    format: 'gen3ou', seed,
    teams: [team(caseID, 0, member('starfberry', initialHP)),
      team(caseID, 1, member(''))],
    source_choices: choices, choices,
    forced_outcomes: selectedStat === undefined ? [] : [{
      label: 'item.starfberry.stat', occurrence: 1, range: 5,
      result: selectedStat,
    }],
    features: ['choice.move', 'effect.boost', 'handler.residual',
      'item.consumption', 'prng.labeled', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`),
    `${JSON.stringify(fixture, null, 2)}\n`);
}

const selectionSeeds = [1, 20, 2, 37, 3];
for (let selected = 0; selected < selectionSeeds.length; selected++) {
  emit(`berry-starf-stat-${selected}`, 62, [701, 23, 41, selectionSeeds[selected]],
    `Starf Berry uniformly selects eligible stat index ${selected}`, selected);
}
emit('berry-starf-above-threshold', 63, [719, 23, 41, 79],
  'Starf Berry remains held immediately above its quarter-HP threshold');

console.log('generated 6 Starf Berry cases');
