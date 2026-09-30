#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-plus-minus-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {Dex, TeamValidator, Teams} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.resolve(__dirname, 'derived');

function member(speciesID, ability, moves) {
  const species = dex.species.get(speciesID);
  const b = species.baseStats;
  return {species: species.id, level: 100, gender: 'M', ability, item: '', moves,
    stats: [2 * b.hp + 141, 2 * b.atk + 36, 2 * b.def + 36,
      2 * b.spa + 36, 2 * b.spd + 36, 2 * b.spe + 36], status: null};
}

function teamSource(team) {
  return team.map(pokemon => `${dex.species.get(pokemon.species).name} (M)\n` +
    `Ability: ${dex.abilities.get(pokemon.ability).name}\nLevel: 100\n` +
    'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
    `${pokemon.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

function writeCase(id, left, right, testName) {
  const teams = [[left], [right]];
  const files = [`${id}-p1.txt`, `${id}-p2.txt`];
  for (let side = 0; side < 2; side++) {
    const source = teamSource(teams[side]);
    const problems = validator.validateTeam(Teams.import(source));
    if (problems) throw new Error(`${id} p${side + 1}: ${problems.join('; ')}`);
    fs.writeFileSync(path.join(out, files[side]), source);
  }
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/mods/gen3/abilities.ts', test_name: testName,
      oracle_revision: revision},
    format: 'gen3ou', seed: [821, 211, 53, 17],
    teams: teams.map((team, side) => ({source: files[side], normalized: team})),
    source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
    forced_outcomes: [],
    features: ['choice.move', 'damage.gen3', 'handler.modify-special-attack',
      'prng.labeled', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers',
      'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

writeCase('plus-minus-opponent-boost',
  member('plusle', 'plus', ['thunderbolt']),
  member('minun', 'minus', ['growl']),
  'An opposing active Minus enables the Gen 3 Plus special-attack modifier');
writeCase('plus-minus-reverse-opponent-boost',
  member('minun', 'minus', ['thunderbolt']),
  member('plusle', 'plus', ['growl']),
  'An opposing active Plus enables the Gen 3 Minus special-attack modifier');
writeCase('plus-minus-same-no-boost',
  member('plusle', 'plus', ['thunderbolt']),
  member('plusle', 'plus', ['growl']),
  'Matching relational abilities do not enable the Gen 3 modifier');
writeCase('plus-minus-physical-control',
  member('plusle', 'plus', ['quickattack']),
  member('minun', 'minus', ['growl']),
  'The relational modifier applies to special attack only');
console.log('generated 4 Plus/Minus differential cases');
