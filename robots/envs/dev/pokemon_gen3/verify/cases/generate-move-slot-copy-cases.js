#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate-move-slot-copy-cases.js SHOWDOWN_DIR');
const revision = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected ${REVISION}, got ${revision}`);
const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const output = path.join(__dirname, 'derived');

function stats(id, speedOffset = 0) {
	const base = dex.species.get(id).baseStats;
	const stat = name => 2 * base[name] + 31;
	return [stat('hp') + 110, stat('atk') + 5, stat('def') + 5,
		stat('spa') + 5, stat('spd') + 5, stat('spe') + 5 + speedOffset];
}
function member(species, ability, moves, speedOffset = 0) {
	return {species, level: 100, gender: 'M', nature: 'hardy', ability,
		item: '', moves, stats: stats(species, speedOffset), status: null};
}
function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (M)\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

const cases = [
	{
		id: 'mimic-copy-switch-reset', moves: ['splash', 'mimic'],
		choices: [
			['move 1', 'move 1'], ['move 2', 'move 1'], ['switch 2', 'move 1'],
		], maxBoundaries: 4,
		test: 'Mimic copies raw PP with destination PP Ups and restores its spent base slot on switch',
	},
	{
		id: 'sketch-copy-switch-persistence', moves: ['sketch', 'splash'],
		choices: [
			['move 2', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 1'],
			['switch 2', 'move 1'],
		], maxBoundaries: 5,
		test: 'Sketch replaces current and base slots and preserves copied PP through switch',
	},
];

for (const spec of cases) {
	const teams = [
		[member('smeargle', 'owntempo', spec.moves),
			member('magikarp', 'swiftswim', ['splash'])],
		[member('corsola', 'naturalcure', ['recover'])],
	];
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	teams.forEach((team, side) => {
		const text = teamText(team);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(output, sources[side]), text);
	});
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/mods/gen4/moves.ts#mimic-sketch',
			test_name: spec.test, oracle_revision: REVISION},
		format: 'gen3ou', seed: [449, 79, 37, spec.id.startsWith('mimic') ? 19 : 23],
		teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'choice.switch', 'state.canonical', 'prng.labeled'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.maxBoundaries, max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(output, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}
console.log(`generated and legality-validated ${cases.length} move-slot copy cases`);
