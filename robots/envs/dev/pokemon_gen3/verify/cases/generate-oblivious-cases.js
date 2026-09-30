#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) {
  throw new Error('usage: generate-oblivious-cases.js POKEMON_SHOWDOWN_DIR');
}
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');

const catalog = {
  delcatty: {name: 'Delcatty', ability: 'cutecharm',
    stats: [281, 166, 166, 146, 146, 176]},
  slowpoke: {name: 'Slowpoke', ability: 'oblivious',
    stats: [321, 166, 166, 116, 116, 66]},
  alakazam: {name: 'Alakazam', ability: 'synchronize',
    stats: [251, 136, 126, 306, 206, 276]},
};
const abilityName = {cutecharm: 'Cute Charm', oblivious: 'Oblivious',
  synchronize: 'Synchronize'};
const moveName = {attract: 'Attract', growl: 'Growl', rest: 'Rest',
  taunt: 'Taunt', psychic: 'Psychic', recover: 'Recover', roleplay: 'Role Play'};

function member(species, gender, moves) {
  const entry = catalog[species];
  return {
    export: `${entry.name} (${gender})\nAbility: ${abilityName[entry.ability]}\n` +
      'Level: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
      `Hardy Nature\n${moves.map(move => `- ${moveName[move]}`).join('\n')}\n`,
    normalized: {species, level: 100, gender, nature: 'hardy',
      ability: entry.ability, item: '', moves, stats: entry.stats, status: null},
  };
}

function team(caseID, side, entries) {
  const source = `${caseID}-p${side + 1}.txt`;
  const text = entries.map(entry => entry.export).join('\n');
  const problems = validator.validateTeam(Teams.import(text));
  if (problems) {
    throw new Error(`${caseID} p${side + 1} is not legal Gen 3 OU: ${problems.join('; ')}`);
  }
  fs.writeFileSync(path.join(out, source), text);
  return {source, normalized: entries.map(entry => entry.normalized)};
}

function emit(id, p1, p2, testName,
  choices = [['move 1', 'move 1']], forcedOutcomes = [], features = []) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/abilities.ts; data/mods/gen5/abilities.ts; sim/pokemon.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [641, 29, 43, 89],
    teams: [team(id, 0, p1), team(id, 1, p2)],
    source_choices: choices.map(pair => [...pair]), choices,
    forced_outcomes: forcedOutcomes,
    features: ['choice.move', 'condition.attract', 'ability.oblivious',
      'handler.immunity', 'state.canonical', ...features],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('attract-oblivious-immunity',
  [member('delcatty', 'F', ['attract', 'growl'])],
  [member('slowpoke', 'M', ['rest', 'growl'])],
  'Oblivious rejects Attract at volatile Immunity after accuracy');
emit('attract-oblivious-taunt-negative',
  [member('alakazam', 'M', ['taunt', 'psychic'])],
  [member('slowpoke', 'F', ['rest', 'growl'])],
  'Gen 3 Oblivious does not prevent modern Taunt semantics');
emit('attract-oblivious-role-play-update',
  [member('alakazam', 'M', ['recover', 'roleplay'])],
  [member('slowpoke', 'F', ['attract', 'rest'])],
  'Role Play gains Oblivious and immediate Gen 3 Update removes Attract',
  [['move 1', 'move 1'], ['move 2', 'move 2']],
  [{label: 'condition.attract.action', occurrence: 1, range: 2, result: 1}],
  ['move.role-play', 'handler.status-update']);
emit('role-play-same-ability-failure',
  [member('alakazam', 'M', ['roleplay', 'recover'])],
  [member('alakazam', 'F', ['recover', 'psychic'])],
  'Role Play rejects copying the same current ability without PRNG',
  [['move 1', 'move 1']], [], ['move.role-play', 'handler.try-hit']);

console.log('generated 4 Oblivious and Role Play cases');
