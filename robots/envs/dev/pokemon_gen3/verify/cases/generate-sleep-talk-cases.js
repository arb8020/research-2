#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate-sleep-talk-cases.js SHOWDOWN_DIR');
const revision = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected ${REVISION}, got ${revision}`);
const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const output = path.join(__dirname, 'derived');

function stats(id) {
	const base = dex.species.get(id).baseStats;
	const stat = name => 2 * base[name] + 31;
	return [stat('hp') + 110, stat('atk') + 5, stat('def') + 5,
		stat('spa') + 5, stat('spd') + 5, stat('spe') + 5];
}
function member(species, ability, moves, status = null) {
	const result = {species, level: 100, gender: 'M', nature: 'hardy', ability,
		item: '', moves, stats: stats(species), status};
	if (status === 'slp') result.status_state = {kind: 'sleep', time: 3, skipped_time: 0};
	return result;
}
function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (M)\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

const cases = [
	{
		id: 'sleep-talk-current-slot-call', asleep: true,
		moves: ['sleeptalk', 'scratch'], seed: [431, 73, 31, 11],
		test: 'Sleep Talk samples one eligible current slot and calls it without deducting child PP',
	},
	{
		id: 'sleep-talk-awake-rejection', asleep: false,
		moves: ['sleeptalk', 'scratch'], seed: [433, 73, 31, 13],
		test: 'Sleep Talk rejects an awake user before selection',
	},
	{
		id: 'sleep-talk-no-eligible-slot', asleep: true,
		moves: ['sleeptalk', 'fly'], seed: [437, 73, 31, 17],
		test: 'Sleep Talk excludes itself and charge moves and fails without selection',
	},
];

for (const spec of cases) {
	const teams = [
		[member('smeargle', 'owntempo', spec.moves, spec.asleep ? 'slp' : null)],
		[member('magikarp', 'swiftswim', ['splash'])],
	];
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	teams.forEach((team, side) => {
		const text = teamText(team);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(output, sources[side]), text);
	});
	const choices = [['move 1', 'move 1']];
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/mods/gen3/moves.ts#sleeptalk',
			test_name: spec.test, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: choices, choices, forced_outcomes: [],
		features: ['choice.move', 'move.called-entry', 'move.slot-delegation',
			'prng.labeled', 'state.canonical', 'status.sleep'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: 2, max_actions: 2},
	});
	fs.writeFileSync(path.join(output, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}
console.log(`generated and legality-validated ${cases.length} Sleep Talk cases`);
