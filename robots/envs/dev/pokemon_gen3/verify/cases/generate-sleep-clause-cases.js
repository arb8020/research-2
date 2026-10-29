#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) {
	throw new Error('usage: generate-sleep-clause-cases.js POKEMON_SHOWDOWN_DIR');
}
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {
	encoding: 'utf8',
}).trim() !== REVISION) throw new Error('wrong Showdown revision');

const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species) {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, gender = 'M') {
	return {species, level: 100, gender, ability, item: '', moves,
		stats: stats(species), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		`EVs: 1 HP\nHardy Nature\n` +
		`${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`)
		.join('\n');
}

const id = 'sleep-clause-rest-self-sleep';
const teams = [
	[member('smeargle', 'owntempo', ['spore', 'tackle'])],
	[member('vaporeon', 'waterabsorb', ['rest']),
		member('magikarp', 'swiftswim', ['splash'])],
];
const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
for (let side = 0; side < 2; side++) {
	const text = teamText(teams[side]);
	const errors = validator.validateTeam(Teams.import(text));
	if (errors) throw new Error(`${id} p${side + 1}: ${errors.join('; ')}`);
	fs.writeFileSync(path.join(out, sources[side]), text);
}

const sourceChoices = [
	['move 1', 'switch 2'],
	['move 2', 'switch 2'],
	['move 2', 'move 1'],
];
const choices = [
	['move 1', 'switch 2'],
	['move 2', 'switch 1'],
	['move 2', 'move 1'],
];
const fixture = normalizeCase({
	schema: 'pokemon-native-differential-case-v1', id,
	provenance: {
		kind: 'showdown-test',
		source_file: 'test/sim/rulesets/sleepclausemod.js',
		test_name: 'Sleep Clause Mod > should not prevent Rest',
		oracle_revision: REVISION,
	},
	format: 'gen3ou', seed: [463, 467, 479, 487],
	teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
	source_choices: sourceChoices, choices, forced_outcomes: [],
	features: [
		'choice.move', 'choice.switch', 'condition.nonvolatile-status',
		'effect.direct-heal', 'prng.labeled', 'rule.sleep-clause',
		'state.canonical', 'status.sleep',
	],
	boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
	limits: {max_boundaries: 4, max_actions: 6},
});
fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);

console.log('generated and legality-validated 1 Sleep Clause fixture');
