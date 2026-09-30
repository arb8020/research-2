#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const path = require('path');

const EXPECTED_REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: oracle.js POKEMON_SHOWDOWN_DIR');
const revision = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}
).trim();
if (revision !== EXPECTED_REVISION) {
  throw new Error(`expected Pokemon Showdown ${EXPECTED_REVISION}, got ${revision}`);
}

const {Battle, Dex} = require(path.resolve(showdownDir));
const inventory = require('../inventory/gen3ou-inventory.json');
const battle = new Battle({formatid: 'gen3ou'});
const dex = Dex.forGen(3);
const statNames = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
const typeNames = [
  'Normal', 'Ghost', 'Psychic', 'Fighting', 'Dark', 'Grass', 'Poison', 'Fire',
  'Flying', 'Ground', 'Water', 'Rock', 'Steel', 'Bug', 'Ice', 'Electric',
  'Dragon', '???',
];
const categories = new Map([['Physical', 1], ['Special', 2], ['Status', 3]]);
const targets = new Map([
  ['adjacentAlly', 1], ['all', 2], ['allAdjacent', 3],
  ['allAdjacentFoes', 4], ['allySide', 5], ['allyTeam', 6], ['any', 7],
  ['foeSide', 8], ['normal', 9], ['randomNormal', 10], ['scripted', 11],
  ['self', 12],
]);
const flagNames = [
  'allyanim', 'bite', 'bullet', 'bypasssub', 'charge', 'contact', 'dance',
  'defrost', 'distance', 'failcopycat', 'failencore', 'failinstruct',
  'failmefirst', 'failmimic', 'futuremove', 'gravity', 'heal', 'metronome',
  'minimize', 'mirror', 'mustpressure', 'noassist', 'nonsky',
  'noparentalbond', 'nosketch', 'nosleeptalk', 'powder', 'protect', 'pulse',
  'punch', 'recharge', 'reflectable', 'slicing', 'snatch', 'sound', 'wind',
];

function executableId(kind, id, sourceNum) {
  const data = require('../../verify/cases/native-id-map.json');
  if (kind === 'species') return data.species[id] || 0;
  if (kind === 'move') return data.moves[id] || 0;
  if (kind === 'ability') return data.abilities[id] ? sourceNum : 0;
  if (kind === 'item') return data.items[id] ? sourceNum : 0;
  throw new Error(`unknown kind: ${kind}`);
}

function set(level, iv, ev) {
  const spread = Object.fromEntries(statNames.map(stat => [stat, iv]));
  const effort = Object.fromEntries(statNames.map(stat => [stat, ev]));
  return {level, ivs: spread, evs: effort, nature: 'Serious'};
}

function speciesRecord(entry, index) {
  const species = dex.species.get(entry.id);
  const vectors = [[1, 0, 0], [50, 31, 0], [100, 31, 252]].map(vector => {
    const result = battle.spreadModify(species.baseStats, set(...vector));
    if (species.maxHP) result.hp = species.maxHP;
    return statNames.map(stat => result[stat]);
  });
  return {
    kind: 'species', catalog_id: index + 1, source_num: species.num,
    executable_id: executableId('species', entry.id, species.num),
    id: species.id, name: species.name, tier: species.tier,
    types: species.types.map(type => typeNames.indexOf(type)),
    base_stats: statNames.map(stat => species.baseStats[stat]),
    max_hp_override: species.maxHP || 0, stat_vectors: vectors,
  };
}

function moveRecord(entry, index) {
  const move = dex.moves.get(entry.id);
  let flags = 0n;
  for (const flag of Object.keys(move.flags || {})) {
    const bit = flagNames.indexOf(flag);
    if (bit < 0) throw new Error(`unmapped move flag ${flag} on ${entry.id}`);
    flags |= 1n << BigInt(bit);
  }
  return {
    kind: 'move', catalog_id: index + 1, source_num: move.num,
    executable_id: executableId('move', entry.id, move.num),
    id: move.id, name: move.name, type: typeNames.indexOf(move.type),
    category: categories.get(move.category), base_power: move.basePower,
    accuracy: move.accuracy === true ? 0 : move.accuracy,
    always_hits: move.accuracy === true ? 1 : 0, priority: move.priority,
    pp: move.pp, max_pp: [0, 1, 2, 3].map(ups => battle.calculatePP(move, ups)),
    target: targets.get(move.target), flags: flags.toString(),
  };
}

function namedRecord(kind, entry, index) {
  const value = kind === 'ability' ? dex.abilities.get(entry.id) : dex.items.get(entry.id);
  return {
    kind, catalog_id: index + 1, source_num: value.num,
    executable_id: executableId(kind, entry.id, value.num),
    id: value.id, name: value.name,
  };
}

const records = [
  ...inventory.species.map(speciesRecord),
  ...inventory.moves.map(moveRecord),
  ...inventory.abilities.map((entry, index) => namedRecord('ability', entry, index)),
  ...inventory.items.map((entry, index) => namedRecord('item', entry, index)),
];
for (const record of records) process.stdout.write(`${JSON.stringify(record)}\n`);
