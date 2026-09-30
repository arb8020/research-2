#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const showdownDir = process.argv[2];
if (!showdownDir) {
  throw new Error('usage: generate-leech-seed-cases.js POKEMON_SHOWDOWN_DIR');
}

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const actualRevision = cp.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'},
).trim();
if (actualRevision !== revision) throw new Error(`wrong Showdown revision: ${actualRevision}`);

const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');
const out = path.resolve(__dirname, 'derived');

const catalog = {
  blissey: {name: 'Blissey', gender: 'F', ability: 'Natural Cure', stats: [651, 56, 56, 186, 306, 146]},
  blastoise: {name: 'Blastoise', gender: 'M', ability: 'Torrent', stats: [299, 202, 236, 206, 246, 192]},
  smeargle: {name: 'Smeargle', gender: 'M', ability: 'Own Tempo', stats: [251, 76, 106, 76, 126, 186]},
  tentacool: {name: 'Tentacool', gender: 'M', ability: 'Liquid Ooze', stats: [221, 116, 106, 136, 236, 176]},
  venusaur: {name: 'Venusaur', gender: 'M', ability: 'Overgrow', stats: [301, 200, 202, 236, 236, 196]},
};

const moveNames = {
  bind: 'Bind', gigadrain: 'Giga Drain', haze: 'Haze',
  leechseed: 'Leech Seed', protect: 'Protect', rapidspin: 'Rapid Spin',
  recover: 'Recover', softboiled: 'Soft-Boiled', spikes: 'Spikes',
  splash: 'Splash', substitute: 'Substitute', synthesis: 'Synthesis', tackle: 'Tackle',
  withdraw: 'Withdraw',
};

function member(species, moves, initialHP) {
  const entry = catalog[species];
  const display = entry.gender === 'N' ? entry.name : `${entry.name} (${entry.gender})`;
  return {
    export: `${display}\nAbility: ${entry.ability}\nLevel: 100\n` +
      'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
      `${moves.map(move => `- ${moveNames[move]}`).join('\n')}\n`,
    normalized: {
      species, level: 100, gender: entry.gender, nature: 'hardy',
      ability: entry.ability.toLowerCase().replace(/ /g, ''), item: '', moves,
      stats: entry.stats, status: null,
      ...(initialHP === undefined ? {} : {initial_hp: initialHP}),
    },
  };
}

function team(id, side, members) {
  const source = `${id}-p${side + 1}.txt`;
  const text = members.map(entry => entry.export).join('\n');
  const problems = validator.validateTeam(Teams.import(text));
  if (problems) throw new Error(`${source}: ${problems.join('; ')}`);
  fs.writeFileSync(path.join(out, source), text);
  return {source, normalized: members.map(entry => entry.normalized)};
}

function emit({id, left, right, choices, forcedOutcomes, testName, features}) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/moves.ts; data/abilities.ts; sim/battle.ts; sim/pokemon.ts',
      test_name: testName,
      oracle_revision: revision,
    },
    format: 'gen3ou', seed: [701, 193, 43, 11],
    teams: [team(id, 0, left), team(id, 1, right)],
    source_choices: choices, choices, forced_outcomes: forcedOutcomes,
    features,
    boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity', 'state', 'events', 'prng', 'terminal'],
    limits: {max_boundaries: 1 + choices.length, max_actions: 2 * choices.length},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit({
  id: 'leech-seed-source-slot-and-target-switch',
  left: [member('smeargle', ['leechseed', 'splash']), member('blissey', ['softboiled'], 500)],
  right: [member('blissey', ['softboiled']), member('venusaur', ['synthesis'])],
  choices: [['move 1', 'move 1'], ['switch 2', 'move 1'], ['move 1', 'switch 2']],
  forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 8}],
  testName: 'Leech Seed follows the source slot and clears on target switch',
  features: ['condition.volatile', 'effect.heal', 'handler.residual', 'lifecycle.source-bound', 'state.canonical'],
});

emit({
  id: 'leech-seed-grass-immunity',
  left: [member('smeargle', ['leechseed', 'splash'])],
  right: [member('venusaur', ['synthesis'])],
  choices: [['move 1', 'move 1']],
  forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 8}],
  testName: 'Leech Seed fails against a Grass target without installing a volatile',
  features: ['condition.volatile', 'hit.type-immunity', 'state.canonical'],
});

emit({
  id: 'leech-seed-liquid-ooze-drain',
  left: [member('venusaur', ['leechseed', 'gigadrain', 'protect', 'tackle'], 220)],
  right: [member('tentacool', ['haze'])],
  choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
  forcedOutcomes: [
    {label: 'move.accuracy', occurrence: 1, range: 100, result: 8},
    {label: 'move.accuracy', occurrence: 2, range: 100, result: 16},
    {label: 'move.critical', occurrence: 1, range: 16, result: 11},
    {label: 'move.damage_roll', occurrence: 1, range: 16, result: 5},
  ],
  testName: 'Liquid Ooze inverts both Leech Seed residual healing and direct drain healing',
  features: ['condition.volatile', 'damage.residual', 'effect.drain', 'effect.heal', 'handler.try-heal', 'state.canonical'],
});

emit({
  id: 'rapid-spin-leech-seed-combined-cleanup',
  left: [member('smeargle', ['leechseed', 'bind', 'spikes', 'splash'])],
  right: [member('blastoise', ['rapidspin', 'withdraw'])],
  choices: [
    ['move 1', 'move 2'], ['move 3', 'move 2'],
    ['move 2', 'move 2'], ['move 4', 'move 1'],
  ],
  forcedOutcomes: [
    {label: 'move.accuracy', occurrence: 1, range: 100, result: 8},
    {label: 'move.accuracy', occurrence: 2, range: 100, result: 73},
    {label: 'move.critical', occurrence: 1, range: 16, result: 5},
    {label: 'move.damage_roll', occurrence: 1, range: 16, result: 12},
    {label: 'condition.partiallytrapped.duration', occurrence: 1, range: 4, result: 2},
    {label: 'move.accuracy', occurrence: 3, range: 100, result: 80},
    {label: 'move.critical', occurrence: 2, range: 16, result: 3},
    {label: 'move.damage_roll', occurrence: 2, range: 16, result: 3},
  ],
  testName: 'A connected Rapid Spin atomically removes Leech Seed, partial trapping, and Spikes',
  features: ['condition.side', 'condition.volatile', 'lifecycle.condition-duration', 'state.canonical'],
});

emit({
  id: 'rapid-spin-leech-seed-substitute-and-protect',
  left: [member('smeargle', ['leechseed', 'substitute', 'protect', 'splash'])],
  right: [member('blastoise', ['rapidspin', 'withdraw'])],
  choices: [
    ['move 1', 'move 2'], ['move 2', 'move 1'],
    ['move 1', 'move 2'], ['move 3', 'move 1'],
  ],
  forcedOutcomes: [
    {label: 'move.accuracy', occurrence: 1, range: 100, result: 8},
    {label: 'move.accuracy', occurrence: 2, range: 100, result: 16},
    {label: 'move.critical', occurrence: 1, range: 16, result: 11},
    {label: 'move.damage_roll', occurrence: 1, range: 16, result: 5},
    {label: 'move.accuracy', occurrence: 3, range: 100, result: 66},
    {label: 'move.accuracy', occurrence: 4, range: 100, result: 80},
  ],
  testName: 'Rapid Spin cleans after Substitute damage but not after Protect prevents damage',
  features: ['condition.volatile', 'hit.protect', 'hit.substitute', 'state.canonical'],
});

console.log('generated 5 Leech Seed/Liquid Ooze/Rapid Spin cases');
