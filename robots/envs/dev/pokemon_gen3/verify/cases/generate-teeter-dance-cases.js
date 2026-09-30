#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const sets = {
  alakazam: {ability: 'Synchronize', stats: [251, 136, 126, 306, 206, 276]},
  persian: {ability: 'Limber', stats: [271, 176, 156, 166, 166, 266]},
  smeargle: {ability: 'Own Tempo', stats: [251, 76, 106, 76, 126, 186]},
  vaporeon: {ability: 'Water Absorb', stats: [401, 166, 156, 256, 226, 166]},
};

const id = text => text.toLowerCase().replace(/[^a-z0-9]+/g, '');
const title = text => ({
  owntempo: 'Own Tempo', teeterdance: 'Teeter Dance', waterabsorb: 'Water Absorb',
})[id(text)] || text[0].toUpperCase() + text.slice(1);

function member(species, moves) {
  const set = sets[species];
  return {
    export: `${title(species)} (M)\nAbility: ${set.ability}\nLevel: 100\n` +
      'EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
      moves.map(move => `- ${title(move)}`).join('\n') + '\n',
    normalized: {species, level: 100, gender: 'M', ability: id(set.ability), item: '',
      moves: moves.map(id), stats: set.stats, status: null},
  };
}

function team(caseID, side, specs) {
  const source = `${caseID}-p${side}.txt`;
  const built = specs.map(spec => member(spec.species, spec.moves));
  fs.writeFileSync(path.join(out, source), built.map(entry => entry.export).join('\n'));
  return {source, normalized: built.map(entry => entry.normalized)};
}

function emit(config) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: config.id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/mods/gen3/moves.ts; data/abilities.ts; sim/battle-actions.ts; sim/battle.ts',
      test_name: config.testName, oracle_revision: revision},
    format: 'gen3ou', seed: config.seed || [761, 43, 19, 7],
    teams: [team(config.id, 'p1', config.p1), team(config.id, 'p2', config.p2)],
    source_choices: config.choices.map(pair => [...pair]), choices: config.choices,
    forced_outcomes: config.forced || [],
    features: ['choice.move', 'condition.volatile', 'hit.accuracy', 'prng.labeled',
      'state.canonical', 'volatile.confusion'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: config.choices.length + 1,
      max_actions: config.choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${config.id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit({id: 'teeterdance-success-duration-action',
  testName: 'Teeter Dance installs confusion and stages duration before same-turn action',
  p1: [{species: 'alakazam', moves: ['teeterdance']}],
  p2: [{species: 'persian', moves: ['splash']}],
  choices: [['move 1', 'move 1']],
  forced: [
    {label: 'condition.confusion.duration', occurrence: 1, range: 4, result: 1},
  ]});

emit({id: 'teeterdance-own-tempo-cancel',
  testName: 'Own Tempo cancels Teeter Dance confusion before duration staging',
  p1: [{species: 'alakazam', moves: ['teeterdance']}],
  p2: [{species: 'smeargle', moves: ['splash']}],
  choices: [['move 1', 'move 1']]});

emit({id: 'teeterdance-substitute-block',
  testName: 'An established Substitute blocks Teeter Dance confusion',
  p1: [{species: 'smeargle', moves: ['teeterdance']}],
  p2: [{species: 'persian', moves: ['substitute']}],
  choices: [['move 1', 'move 1']]});

emit({id: 'teeterdance-protect-block',
  testName: 'Protect blocks Teeter Dance before confusion duration staging',
  p1: [{species: 'alakazam', moves: ['teeterdance']}],
  p2: [{species: 'persian', moves: ['protect']}],
  choices: [['move 1', 'move 1']]});

emit({id: 'teeterdance-switch-clear-reapply',
  testName: 'Switching clears Teeter Dance confusion and permits fresh application',
  p1: [{species: 'alakazam', moves: ['teeterdance', 'splash']}],
  p2: [{species: 'persian', moves: ['splash']}, {species: 'vaporeon', moves: ['splash']}],
  choices: [['move 1', 'move 1'], ['move 2', 'switch 2'], ['move 1', 'move 1']],
  forced: []});

console.log('generated 5 Teeter Dance cases');
