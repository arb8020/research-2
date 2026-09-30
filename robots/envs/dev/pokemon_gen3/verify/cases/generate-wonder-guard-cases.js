#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-wonder-guard-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');

const catalog = {
  smeargle: {name: 'Smeargle', ability: 'Own Tempo', stats: [251, 76, 106, 76, 126, 186]},
  shedinja: {name: 'Shedinja', ability: 'Wonder Guard', stats: [1, 216, 126, 96, 96, 116]},
  blissey: {name: 'Blissey', ability: 'Natural Cure', stats: [651, 56, 56, 186, 306, 146]},
};
const moveName = {watergun: 'Water Gun', ember: 'Ember', growl: 'Growl',
  tackle: 'Tackle', roleplay: 'Role Play', splash: 'Splash', protect: 'Protect'};
moveName.thief = 'Thief';
moveName.softboiled = 'Soft-Boiled';

function member(species, moves) {
  const entry = catalog[species];
  const gender = species === 'shedinja' ? 'N' : species === 'blissey' ? 'F' : 'M';
  const display = gender === 'N' ? entry.name : `${entry.name} (${gender})`;
  return {
    export: `${display}\nAbility: ${entry.ability}\nLevel: 100\n` +
      'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
      `${moves.map(move => `- ${moveName[move]}`).join('\n')}\n`,
    normalized: {species, level: 100, gender, nature: 'hardy',
      ability: entry.ability.toLowerCase().replace(/ /g, ''), item: '', moves,
      stats: entry.stats, status: null},
  };
}

function team(caseID, side, entries) {
  const source = `${caseID}-p${side + 1}.txt`;
  const text = entries.map(entry => entry.export).join('\n');
  const problems = validator.validateTeam(Teams.import(text));
  if (problems) throw new Error(`${caseID} p${side + 1}: ${problems.join('; ')}`);
  fs.writeFileSync(path.join(out, source), text);
  return {source, normalized: entries.map(entry => entry.normalized)};
}

function emit(id, p1, p2, choices, testName) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/mods/gen4/abilities.ts; sim/battle-actions.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [719, 31, 47, 101],
    teams: [team(id, 0, p1), team(id, 1, p2)],
    source_choices: choices.map(pair => [...pair]), choices,
    forced_outcomes: [],
    features: ['choice.move', 'ability.wonder-guard', 'handler.try-hit',
      'hit.immunity-cause', 'state.canonical', 'prng.labeled'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity',
      'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('wonder-guard-effectiveness',
  [member('smeargle', ['watergun', 'ember'])],
  [member('shedinja', ['thief']), member('blissey', ['softboiled'])],
  [['move 1', 'move 1'], ['move 2', 'move 1']],
  'neutral damage is rejected while super-effective damage connects');
emit('wonder-guard-bypass-and-order',
  [member('smeargle', ['growl', 'watergun', 'tackle', 'roleplay'])],
  [member('shedinja', ['thief', 'protect']), member('blissey', ['softboiled'])],
  [['move 1', 'move 1'], ['move 2', 'move 2'], ['move 3', 'move 1'],
    ['move 4', 'move 1']],
  'status bypass, Protect precedence, natural immunity, and transfer rejection');

console.log('generated 2 Wonder Guard cases');
