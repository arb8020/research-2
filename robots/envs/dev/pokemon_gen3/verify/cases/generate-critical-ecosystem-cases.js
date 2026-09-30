#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-critical-ecosystem-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'],
  {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {Dex} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const outputDir = path.resolve(__dirname, 'derived');

function stats(id) {
  const b = dex.species.get(id).baseStats;
  return [2 * b.hp + 141, 2 * b.atk + 36, 2 * b.def + 36,
    2 * b.spa + 36, 2 * b.spd + 36, 2 * b.spe + 36];
}
function member(species, ability, moves, item = '') {
  const value = dex.species.get(species);
  return {species: value.id, level: 100,
    gender: value.gender === 'N' ? 'N' : value.gender === 'F' ? 'F' : 'M',
    ability, item, moves, stats: stats(value.id), status: null};
}
function teamText(team) {
  return team.map(value => {
    const species = dex.species.get(value.species);
    const sex = value.gender === 'N' ? '' : ` (${value.gender})`;
    const item = value.item ? ` @ ${dex.items.get(value.item).name}` : '';
    return `${species.name}${sex}${item}\nAbility: ${dex.abilities.get(value.ability).name}\n` +
      'Level: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
      `Hardy Nature\n${value.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`;
  }).join('\n');
}
function writeCase(id, left, right, choices, forcedOutcomes, features) {
  const p1 = `${id}-p1.txt`, p2 = `${id}-p2.txt`;
  fs.writeFileSync(path.join(outputDir, p1), teamText(left));
  fs.writeFileSync(path.join(outputDir, p2), teamText(right));
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/items.ts; data/abilities.ts; sim/battle-actions.ts',
      test_name: id, oracle_revision: revision},
    format: 'gen3ou', seed: [419, 223, 107, 53],
    teams: [{source: p1, normalized: left}, {source: p2, normalized: right}],
    source_choices: choices, choices, forced_outcomes: forcedOutcomes,
    features: ['choice.move', 'damage.critical', 'handler.modify-crit-ratio',
      'prng.labeled', 'state.canonical', ...features],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(outputDir, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

const splash = [member('blissey', 'naturalcure', ['splash'])];
writeCase('critical-focus-energy',
  [member('smeargle', 'owntempo', ['focusenergy', 'slash'])], splash,
  [['move 1', 'move 1'], ['move 2', 'move 1']],
  [{label: 'move.critical', occurrence: 1, range: 3, result: 0}],
  ['condition.volatile', 'volatile.focus-energy']);
writeCase('critical-focus-energy-duplicate',
  [member('smeargle', 'owntempo', ['focusenergy'])], splash,
  [['move 1', 'move 1'], ['move 1', 'move 1']], [],
  ['condition.volatile', 'volatile.focus-energy']);
writeCase('critical-focus-energy-switch-cleanup',
  [member('smeargle', 'owntempo', ['focusenergy']), member('spearow', 'keeneye', ['slash'])],
  [member('blissey', 'naturalcure', ['splash']), member('tyrogue', 'guts', ['splash'])],
  [['move 1', 'move 1'], ['switch 2', 'switch 2']], [],
  ['choice.switch', 'condition.volatile', 'volatile.focus-energy']);
writeCase('critical-focus-energy-snatched',
  [member('smeargle', 'owntempo', ['focusenergy'])],
  [member('persian', 'limber', ['snatch'])],
  [['move 1', 'move 1']], [], ['move.snatch', 'volatile.focus-energy']);
writeCase('critical-scope-lens',
  [member('smeargle', 'owntempo', ['slash'], 'scopelens')], splash,
  [['move 1', 'move 1']],
  [{label: 'move.critical', occurrence: 1, range: 4, result: 0}],
  ['item.scope-lens']);
writeCase('critical-lucky-punch-chansey',
  [member('chansey', 'naturalcure', ['tackle'], 'luckypunch')], splash,
  [['move 1', 'move 1']],
  [{label: 'move.critical', occurrence: 1, range: 4, result: 0}],
  ['item.lucky-punch', 'handler.species-guard']);
writeCase('critical-lucky-punch-mismatch',
  [member('blissey', 'naturalcure', ['tackle'], 'luckypunch')],
  [member('chansey', 'naturalcure', ['splash'])],
  [['move 1', 'move 1']], [],
  ['item.lucky-punch', 'handler.species-guard']);
writeCase('critical-stick-farfetchd',
  [member('farfetchd', 'keeneye', ['slash'], 'stick')], splash,
  [['move 1', 'move 1']],
  [{label: 'move.critical', occurrence: 1, range: 3, result: 0}],
  ['item.stick', 'handler.species-guard']);
writeCase('critical-stick-mismatch',
  [member('spearow', 'keeneye', ['slash'], 'stick')], splash,
  [['move 1', 'move 1']], [],
  ['item.stick', 'handler.species-guard']);
writeCase('critical-battle-armor-cancel',
  [member('smeargle', 'owntempo', ['slash'])],
  [member('kabuto', 'battlearmor', ['splash'])],
  [['move 1', 'move 1']],
  [{label: 'move.critical', occurrence: 1, range: 8, result: 0}],
  ['ability.battle-armor', 'handler.critical-hit-cancel']);
writeCase('critical-shell-armor-cancel',
  [member('smeargle', 'owntempo', ['slash'])],
  [member('torkoal', 'shellarmor', ['splash'])],
  [['move 1', 'move 1']],
  [{label: 'move.critical', occurrence: 1, range: 8, result: 0}],
  ['ability.shell-armor', 'handler.critical-hit-cancel']);

console.log('generated 11 critical ecosystem differential cases');
