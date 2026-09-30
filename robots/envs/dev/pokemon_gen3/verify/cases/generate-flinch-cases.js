#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-flinch-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {Dex} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const outputDir = path.resolve(__dirname, 'derived');
const rotations = [
  ['astonish', 'extrasensory', 'needlearm', 'boneclub'],
  ['hyperfang', 'rollingkick', 'bite', 'headbutt'],
  ['rockslide', 'stomp', 'twister'],
];

function stats(species) {
  const b = species.baseStats;
  return [2 * b.hp + 141, 2 * b.atk + 36, 2 * b.def + 36,
    2 * b.spa + 36, 2 * b.spd + 36, 2 * b.spe + 36];
}
function member(speciesID, ability, moves) {
  const species = dex.species.get(speciesID);
  return {species: species.id, level: 100,
    gender: species.gender === 'N' ? 'N' : species.gender === 'F' ? 'F' : 'M',
    ability, item: '', moves, stats: stats(species), status: null};
}
function source(member) {
  const species = dex.species.get(member.species);
  const sex = member.gender === 'N' ? '' : ` (${member.gender})`;
  return `${species.name}${sex}\nAbility: ${dex.abilities.get(member.ability).name}\n` +
    `Level: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
    `Hardy Nature\n${member.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`;
}
function writeCase(id, seed, left, right, choices, features) {
  const p1 = `${id}-p1.txt`, p2 = `${id}-p2.txt`;
  fs.writeFileSync(path.join(outputDir, p1), source(left));
  fs.writeFileSync(path.join(outputDir, p2), source(right));
  const battleCase = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/conditions.ts; sim/battle-actions.ts; sim/pokemon.ts',
      test_name: id, oracle_revision: revision},
    format: 'gen3ou', seed,
    teams: [{source: p1, normalized: [left]}, {source: p2, normalized: [right]}],
    source_choices: choices, choices,
    forced_outcomes: [], features,
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(outputDir, `${id}.json`),
    `${JSON.stringify(battleCase, null, 2)}\n`);
}

for (const [index, moves] of rotations.entries()) {
  for (const id of moves) {
    const secondary = dex.moves.get(id).secondary;
    if (!secondary || secondary.volatileStatus !== 'flinch') {
      throw new Error(`resolved flinch secondary changed: ${id}`);
    }
  }
  const left = member('smeargle', 'owntempo', moves);
  const right = member('golem', 'rockhead', ['splash']);
  writeCase(`flinch-rotation-${index + 1}`, [313, 197, 83, 80 + index],
    left, right, moves.map((_, slot) => [`move ${slot + 1}`, 'move 1']),
    ['choice.move', 'volatile.flinch', 'effect.secondary',
      'handler.before-move', 'prng.secondary', 'state.canonical']);
}

writeCase('flinch-inner-focus', [313, 197, 83, 91],
  member('smeargle', 'owntempo', ['bite']),
  member('golem', 'innerfocus', ['splash']),
  Array.from({length: 4}, () => ['move 1', 'move 1']),
  ['ability.inner-focus', 'volatile.flinch', 'effect.secondary',
    'handler.try-add-volatile', 'prng.secondary', 'state.canonical']);

console.log('generated 4 flinch differential cases');
