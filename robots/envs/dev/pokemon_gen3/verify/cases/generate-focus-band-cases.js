#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-focus-band-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');
const catalog = {
  metagross: {name: 'Metagross', ability: 'Clear Body', stats: [301, 306, 296, 226, 216, 176]},
  alakazam: {name: 'Alakazam', ability: 'Synchronize', stats: [251, 136, 126, 306, 206, 276]},
  smeargle: {name: 'Smeargle', ability: 'Own Tempo', stats: [251, 76, 106, 76, 126, 186]},
  persian: {name: 'Persian', ability: 'Limber', stats: [271, 176, 156, 166, 166, 266]},
};
const names = {explosion: 'Explosion', tackle: 'Tackle', recover: 'Recover', growl: 'Growl'};
function member(species, moves, item = '') {
  const e = catalog[species];
  const gender = species === 'metagross' ? 'N' : 'M';
  const display = gender === 'N' ? e.name : `${e.name} (${gender})`;
  return {export: `${display}${item ? ` @ ${item}` : ''}\nAbility: ${e.ability}\nLevel: 100\n` +
    'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
    `${moves.map(m => `- ${names[m]}`).join('\n')}\n`,
  normalized: {species, level: 100, gender, nature: 'hardy',
    ability: e.ability.toLowerCase().replace(/ /g, ''),
    item: item.toLowerCase().replace(/ /g, ''), moves, stats: e.stats, status: null}};
}
function team(id, side, members) {
  const source = `${id}-p${side + 1}.txt`; const text = members.map(x => x.export).join('\n');
  const problems = validator.validateTeam(Teams.import(text));
  if (problems) throw new Error(`${id} p${side + 1}: ${problems.join('; ')}`);
  fs.writeFileSync(path.join(out, source), text);
  return {source, normalized: members.map(x => x.normalized)};
}
function emit(id, left, right, forced, testName, seedTail = 107) {
  const choices = [['move 1', 'move 1']];
  const fixture = {schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived', source_file: 'data/items.ts', test_name: testName,
      oracle_revision: revision}, format: 'gen3ou', seed: [733, 37, 53, seedTail],
    teams: [team(id, 0, left), team(id, 1, right)], source_choices: choices, choices,
    forced_outcomes: [{label: 'item.focus_band', occurrence: 1, range: 10, result: forced}],
    features: ['choice.move', 'item.focus-band', 'handler.damage', 'prng.labeled',
      'state.canonical'], boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2}};
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}
emit('focus-band-lethal-success', [member('metagross', ['explosion'])],
	[member('alakazam', ['recover'], 'Focus Band')], 0, 'lethal move damage is capped at one', 6);
emit('focus-band-lethal-failure', [member('metagross', ['explosion'])],
	[member('alakazam', ['recover'], 'Focus Band')], 3, 'failed activation permits lethal damage', 2);
emit('focus-band-nonlethal-draw', [member('smeargle', ['tackle'])],
	[member('persian', ['growl'], 'Focus Band')], 2, 'the item draw precedes the lethal predicate', 23);
console.log('generated 3 Focus Band cases');
