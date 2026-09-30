#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-source-trap-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');

const catalog = {
  smeargle: {name: 'Smeargle', ability: 'Own Tempo', stats: [251, 76, 106, 76, 126, 186]},
  persian: {name: 'Persian', ability: 'Limber', stats: [271, 176, 156, 166, 166, 266]},
  blissey: {name: 'Blissey', ability: 'Natural Cure', stats: [651, 56, 56, 186, 306, 146]},
  starmie: {name: 'Starmie', ability: 'Natural Cure', stats: [261, 186, 206, 236, 206, 266]},
};
const moveName = {block: 'Block', meanlook: 'Mean Look', spiderweb: 'Spider Web',
  splash: 'Splash', scratch: 'Scratch', pound: 'Pound', recover: 'Recover'};
function member(species, gender, moves) {
  const entry = catalog[species];
  return {
    export: `${entry.name}${gender === 'N' ? '' : ` (${gender})`}\nAbility: ${entry.ability}\nLevel: 100\n` +
      'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
      `${moves.map(move => `- ${moveName[move]}`).join('\n')}\n`,
    normalized: {species, level: 100, gender, nature: 'hardy',
      ability: entry.ability.toLowerCase().replaceAll(' ', ''), item: '', moves,
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
function emit(id, trapMove, choices) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/conditions.ts; sim/pokemon.ts',
      test_name: `${moveName[trapMove]} linked source-owned trapping`,
      oracle_revision: revision},
    format: 'gen3ou', seed: [761, 29, 43, 97],
    teams: [
      team(id, 0, [member('smeargle', 'M', [trapMove, 'splash']),
        member('persian', 'M', ['scratch'])]),
      team(id, 1, [member('blissey', 'F', ['pound']),
        member('starmie', 'N', ['recover'])]),
    ],
    source_choices: choices.map(pair => [...pair]), choices,
    forced_outcomes: [],
    features: ['choice.move', 'choice.switch', 'condition.trapped', 'move.source-trap',
      'handler.trap-pokemon', 'lifecycle.source-bound', 'request.legal-choices',
      'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('source-trap-block-release', 'block',
  [['move 1', 'move 1'], ['switch 2', 'move 1']]);
emit('source-trap-mean-look-rotation', 'meanlook', [['move 1', 'move 1']]);
emit('source-trap-spider-web-rotation', 'spiderweb', [['move 1', 'move 1']]);
console.log('generated 3 source-linked trapping cases');
