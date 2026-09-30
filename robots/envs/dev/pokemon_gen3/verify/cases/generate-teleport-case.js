#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-teleport-case.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);

const {Dex, TeamValidator, Teams} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.resolve(__dirname, 'derived');

function member(speciesID, ability, moves) {
  const species = dex.species.get(speciesID);
  const stats = species.baseStats;
  return {
    species: species.id, level: 100,
    gender: species.gender === 'N' ? 'N' : species.gender === 'F' ? 'F' : 'M',
    ability, item: '', moves,
    stats: [2 * stats.hp + 141, 2 * stats.atk + 36, 2 * stats.def + 36,
      2 * stats.spa + 36, 2 * stats.spd + 36, 2 * stats.spe + 36],
    status: null,
  };
}

function teamSource(team) {
  return team.map(pokemon => {
    const species = dex.species.get(pokemon.species);
    const sex = pokemon.gender === 'N' ? '' : ` (${pokemon.gender})`;
    return `${species.name}${sex}\nAbility: ${dex.abilities.get(pokemon.ability).name}\n` +
      'Level: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
      `Hardy Nature\n${pokemon.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`;
  }).join('\n');
}

const id = 'teleport-declarative-rejection';
const teams = [
  [member('smeargle', 'owntempo', ['teleport'])],
  [member('magikarp', 'swiftswim', ['splash'])],
];
const files = [`${id}-p1.txt`, `${id}-p2.txt`];
for (let side = 0; side < 2; side++) {
  const source = teamSource(teams[side]);
  const problems = validator.validateTeam(Teams.import(source));
  if (problems) throw new Error(`p${side + 1} is not legal Gen 3 OU: ${problems.join('; ')}`);
  fs.writeFileSync(path.join(out, files[side]), source);
}

const battleCase = {
  schema: 'pokemon-native-differential-case-v1', id,
  provenance: {
    kind: 'showdown-derived',
    source_file: 'data/mods/gen7/moves.ts (inherited by resolved Gen 3 ModdedDex)',
    test_name: 'Gen 3 Teleport is a constant-false move-owned Try callback',
    oracle_revision: revision,
  },
  format: 'gen3ou', seed: [733, 97, 41, 13],
  teams: teams.map((team, side) => ({source: files[side], normalized: team})),
  source_choices: [['move 1', 'move 1']],
  choices: [['move 1', 'move 1']],
  forced_outcomes: [],
  features: ['choice.move', 'handler.try', 'prng.labeled', 'state.canonical'],
  boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
  limits: {max_boundaries: 2, max_actions: 2},
};
fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(battleCase, null, 2)}\n`);
console.log('generated Teleport declarative-rejection case');
