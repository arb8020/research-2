#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-leppa-berry-cases.js POKEMON_SHOWDOWN_DIR');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const actual = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');
const out = path.resolve(__dirname, 'derived');
const catalog = {
  smeargle: {name: 'Smeargle', ability: 'Own Tempo', stats: [251, 76, 106, 76, 126, 186]},
  alakazam: {name: 'Alakazam', ability: 'Synchronize', stats: [251, 136, 126, 306, 206, 276]},
  magikarp: {name: 'Magikarp', ability: 'Swift Swim', stats: [181, 56, 146, 66, 76, 196]},
};
const names = {splash: 'Splash', psychup: 'Psych Up', healbell: 'Heal Bell',
  lockon: 'Lock-On', recover: 'Recover', trick: 'Trick'};
function member(species, moves, item = '') {
  const e = catalog[species];
  return {export: `${e.name} (M)${item ? ` @ ${item}` : ''}\nAbility: ${e.ability}\nLevel: 100\n` +
    'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
    `${moves.map(m => `- ${names[m]}`).join('\n')}\n`, normalized: {species, level: 100,
      gender: 'M', nature: 'hardy', ability: e.ability.toLowerCase().replace(/ /g, ''),
      item: item.toLowerCase().replace(/ /g, ''), moves, stats: e.stats, status: null}};
}
function team(id, side, members) {
  const source = `${id}-p${side + 1}.txt`; const text = members.map(x => x.export).join('\n');
  const problems = validator.validateTeam(Teams.import(text));
  if (problems) throw new Error(`${source}: ${problems.join('; ')}`);
  fs.writeFileSync(path.join(out, source), text);
  return {source, normalized: members.map(x => x.normalized)};
}
function emit(id, left, right, choices, testName) {
  const fixture = {schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived', source_file: 'data/items.ts', test_name: testName,
      oracle_revision: revision}, format: 'gen3ou', seed: [743, 154, 10, 3],
    teams: [team(id, 0, left), team(id, 1, right)], source_choices: choices, choices,
    forced_outcomes: [], features: ['choice.move', 'item.leppa-berry', 'handler.update',
      'handler.item-eat', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2}};
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}
emit('leppa-exact-ten-nonfirst',
  [member('smeargle', ['splash', 'psychup'], 'Leppa Berry')],
  [member('magikarp', ['splash'])],
  Array.from({length: 16}, () => ['move 2', 'move 1']),
  'zero PP after base deduction restores exactly ten to a non-first slot');
const delayed = [
  ...Array.from({length: 8}, () => ['move 1', 'move 1']),
  ...Array.from({length: 8}, () => ['move 2', 'move 1']),
  ['move 3', 'move 2'],
];
emit('leppa-delayed-acquisition-first-zero',
  [member('smeargle', ['healbell', 'lockon', 'splash'])],
  [member('alakazam', ['recover', 'trick'], 'Leppa Berry')], delayed,
  'Update after Trick consumes immediately and restores the first zero slot');
console.log('generated 2 Leppa Berry cases');
