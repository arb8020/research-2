#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) {
	throw new Error('usage: node generate-sleep-talk-gate-cases.js SHOWDOWN_DIR');
}
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

function member(species, ability, moves, {item = '', asleep = false} = {}) {
	const result = {species, level: 100, gender: 'M', nature: 'hardy', ability,
		item, moves, stats: stats(species), status: asleep ? 'slp' : null};
	if (asleep) result.status_state = {kind: 'sleep', time: 3, skipped_time: 0};
	return result;
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (M)` +
		`${set.item ? ` @ ${dex.items.get(set.item).name}` : ''}\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

const cases = [
	{
		id: 'sleep-talk-choice-lock-subsequent-rejection',
		seed: [463, 73, 31, 19],
		teams: [
			[member('smeargle', 'owntempo', ['sleeptalk', 'scratch'],
				{item: 'choiceband', asleep: true})],
			[member('magikarp', 'swiftswim', ['splash'])],
		],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1']],
		test: 'Choice Band installs Choice Lock after the first Sleep Talk; the second parent spends PP but TryHit rejects before child selection',
	},
	{
		id: 'sleep-talk-encore-subsequent-rejection',
		seed: [467, 73, 31, 23],
		teams: [
			[member('smeargle', 'owntempo', ['sleeptalk', 'scratch'], {asleep: true})],
			[member('machop', 'guts', ['encore', 'rest'])],
		],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2']],
		test: 'A slower foe legally Encores Sleep Talk; the forced second parent spends PP but TryHit rejects before child selection',
	},
];

for (const spec of cases) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	spec.teams.forEach((team, side) => {
		const text = teamText(team);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(output, sources[side]), text);
	});
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/mods/gen4/moves.ts#sleeptalk; data/mods/gen3/moves.ts#sleeptalk',
			test_name: spec.test, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'condition.volatile',
			'move.called-entry', 'move.slot-delegation', 'prng.labeled',
			'request.legal-choices', 'state.canonical', 'status.sleep'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: 3, max_actions: 4},
	});
	fs.writeFileSync(path.join(output, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

console.log(`generated and legality-validated ${cases.length} Sleep Talk gate cases`);
