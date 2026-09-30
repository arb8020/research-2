#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) {
  throw new Error('usage: generate-freeze-lifecycle-cases.js POKEMON_SHOWDOWN_DIR');
}
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);

const {Dex, TeamValidator, Teams} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const outputDir = path.resolve(__dirname, 'derived');

function stats(species) {
  const b = species.baseStats;
  return [2 * b.hp + 141, 2 * b.atk + 36, 2 * b.def + 36,
    2 * b.spa + 36, 2 * b.spd + 36, 2 * b.spe + 36];
}

function member(speciesID, ability, moves, status = null) {
  const species = dex.species.get(speciesID);
  return {
    species: species.id,
    level: 100,
    gender: species.gender === 'N' ? 'N' : species.gender === 'F' ? 'F' : 'M',
    ability,
    item: '',
    moves,
    stats: stats(species),
    status,
  };
}

function source(pokemon) {
  const species = dex.species.get(pokemon.species);
  const sex = pokemon.gender === 'N' ? '' : ` (${pokemon.gender})`;
  return `${species.name}${sex}\nAbility: ${dex.abilities.get(pokemon.ability).name}\n` +
    'Level: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
    `Hardy Nature\n${pokemon.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`;
}

function writeCase(id, seed, left, right, choices, forcedOutcomes, handlers, testName) {
  const p1 = `${id}-p1.txt`;
  const p2 = `${id}-p2.txt`;
  const p1Source = source(left);
  const p2Source = source(right);
  for (const [side, teamSource] of [[1, p1Source], [2, p2Source]]) {
    const problems = validator.validateTeam(Teams.import(teamSource));
    if (problems) throw new Error(`${id} p${side} is not legal Gen 3 OU: ${problems.join('; ')}`);
  }
  fs.writeFileSync(path.join(outputDir, p1), p1Source);
  fs.writeFileSync(path.join(outputDir, p2), p2Source);
  const battleCase = {
    schema: 'pokemon-native-differential-case-v1',
    id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/conditions.ts; data/mods/gen4/conditions.ts; data/mods/gen3/conditions.ts',
      test_name: testName,
      oracle_revision: revision,
    },
    format: 'gen3ou',
    seed,
    teams: [{source: p1, normalized: [left]}, {source: p2, normalized: [right]}],
    source_choices: choices,
    choices,
    forced_outcomes: forcedOutcomes,
    features: ['condition.nonvolatile-status', ...handlers, 'prng.labeled',
      'state.canonical', 'status.freeze'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(outputDir, `${id}.json`),
    `${JSON.stringify(battleCase, null, 2)}\n`);
}

const freeze = dex.conditions.get('frz');
if (typeof freeze.onStart !== 'function' || typeof freeze.onBeforeMove !== 'function' ||
    typeof freeze.onModifyMove !== 'function' || typeof freeze.onDamagingHit !== 'function') {
  throw new Error('resolved Gen 3 freeze lifecycle changed');
}
if (!dex.moves.get('flamewheel').flags.defrost) {
  throw new Error('Flame Wheel must remain a defrost move');
}
if (dex.moves.get('ember').type !== 'Fire' || dex.moves.get('ember').secondary?.status !== 'brn') {
  throw new Error('Ember Fire/burn semantics changed');
}

writeCase('freeze-lifecycle-random-thaw', [17, 29, 43, 60],
  member('blissey', 'naturalcure', ['icebeam', 'softboiled']),
  member('smeargle', 'owntempo', ['scratch']),
  [['move 1', 'move 1'], ['move 2', 'move 1']],
  [
    {label: 'move.secondary', occurrence: 1, range: 100, result: 1},
    {label: 'status.freeze.before_move', occurrence: 1, range: 5, result: 0},
  ],
  ['effect.secondary', 'handler.before-move'],
  'Ice Beam installs freeze through Start, then Gen 3 random thaw succeeds on the next turn');

writeCase('freeze-lifecycle-defrost', [17, 29, 43, 1],
  member('smeargle', 'owntempo', ['flamewheel'], 'frz'),
  member('magikarp', 'swiftswim', ['splash']),
  [['move 1', 'move 1']],
  [{label: 'status.freeze.before_move', occurrence: 1, range: 5, result: 1}],
  ['handler.before-move', 'handler.modify-move'],
  'Gen 3 failed random thaw permits a defrost move and ModifyMove cures its user');

writeCase('freeze-lifecycle-fire-hit', [17, 29, 43, 19],
  member('charizard', 'blaze', ['ember']),
  member('magikarp', 'swiftswim', ['splash'], 'frz'),
  [['move 1', 'move 1']],
  [{label: 'move.secondary', occurrence: 1, range: 100, result: 1}],
  ['handler.damaging-hit'],
  'Gen 3 Fire damaging hit thaws after a burn secondary is rejected');

console.log('generated 3 freeze lifecycle differential cases');
