#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-rollout-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {
	encoding: 'utf8',
}).trim() !== REVISION) throw new Error('wrong Showdown revision');

const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species) {
	const data = dex.species.get(species);
	const scaled = stat => 2 * data.baseStats[stat] + 31;
	return [species === 'shedinja' ? 1 : scaled('hp') + 110,
		scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, gender = 'M', status = null) {
	return {species, level: 100, gender, ability, item: '', moves,
		stats: stats(species), status};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name}${
		set.gender === 'N' ? '' : ` (${set.gender})`}\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		`EVs: 1 HP\nHardy Nature\n` +
		`${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`)
		.join('\n');
}

function outcomes(label, range, results) {
	return results.map((result, index) => ({
		label, occurrence: index + 1, range, result,
	}));
}

function hitDraws(accuracy, critical, damage) {
	return [
		...outcomes('move.accuracy', 100, accuracy),
		...outcomes('move.critical', 16, critical),
		...outcomes('move.damage_roll', 16, damage),
	];
}

function emit(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(out, sources[side]), text);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/moves.ts#rollout,data/moves.ts#iceball; test/sim/moves/rollout.js:18,42,72,100',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes,
		features: ['choice.move', 'request.legal-choices', 'condition.volatile',
			'handler.base-power', 'handler.damaging-hit', 'hit.accuracy',
			'lifecycle.condition-duration', 'prng.labeled', 'state.canonical',
			...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity',
			'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = (moves, status = null) => member('smeargle', 'owntempo', moves, 'M', status);
const steelix = moves => member('steelix', 'sturdy', moves, 'M');
const cloyster = moves => member('cloyster', 'shellarmor', moves, 'M');
const cycleDraws = hitDraws(
	[28, 34, 18, 43, 4, 9],
	[10, 6, 9, 10, 7, 7],
	[10, 8, 0, 0, 11, 1]);

for (const rotation of [
	{move: 'rollout', fixture: 'rollout', target: steelix(['harden'])},
	{move: 'iceball', fixture: 'ice-ball', target: cloyster(['withdraw'])},
]) {
	emit({
		id: `${rotation.fixture}-defense-curl-cycle`,
		description: `${rotation.move} has Defense Curl-adjusted base powers 60, 120, 240, 480, 960, then 60`,
		seed: [0, 71, 29, 7],
		teams: [[smeargle(['defensecurl', rotation.move])], [rotation.target]],
		choices: [
			['move 1', 'move 1'], ['move 2', 'move 1'],
			...Array.from({length: 4}, () => ['move 1', 'move 1']),
			['move 2', 'move 1'],
		],
		forcedOutcomes: cycleDraws,
		features: ['effect.boost'],
	});
}

const resetDraws = [
	...outcomes('status.paralysis.before_move', 4, [2, 1, 3, 1, 0, 2]),
	...hitDraws([3, 60, 38, 68, 4], [6, 15, 6, 11, 9], [5, 2, 15, 4, 11]),
];
for (const rotation of [{move: 'rollout', fixture: 'rollout'},
	{move: 'iceball', fixture: 'ice-ball'}]) {
	emit({
		id: `${rotation.fixture}-miss-immobilize-reset`,
		description: `${rotation.move} resets after a miss and independently after full paralysis`,
		seed: [5, 71, 29, 3],
		teams: [[smeargle([rotation.move], 'par')], [steelix(['harden'])]],
		choices: Array.from({length: 6}, () => ['move 1', 'move 1']),
		forcedOutcomes: resetDraws,
		features: ['status.paralysis', 'handler.move-aborted'],
	});
}

emit({
	id: 'rollout-protect-ko-replace-roar-reset',
	description: 'Protect blocks after accuracy; Rollout persists through target replacement and resets when Roar switches its source',
	seed: [0, 71, 29, 7],
	teams: [
		[smeargle(['rollout']), member('magikarp', 'swiftswim', ['splash'])],
		[member('shedinja', 'wonderguard', ['protect', 'sandattack'], 'N'),
			steelix(['roar', 'harden'])],
	],
	choices: [
		['move 1', 'move 1'], ['move 1', 'move 2'], [null, 'switch 2'],
		['move 1', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 2'],
	],
	forcedOutcomes: hitDraws([14, 67, 52, 60, 43, 31], [15, 12, 0], [5, 2, 7]),
	features: ['volatile.protect', 'lifecycle.faint', 'lifecycle.forced-replacement',
		'lifecycle.switch-persistence'],
});

emit({
	id: 'ice-ball-wonder-guard-reset',
	description: 'Wonder Guard blocks after accuracy and the rejected Ice Ball ramp expires before its next target',
	seed: [1, 71, 29, 7],
	teams: [[smeargle(['iceball'])], [
		member('shedinja', 'wonderguard', ['swordsdance'], 'N'),
		cloyster(['withdraw']),
	]],
	choices: [['move 1', 'move 1'], ['move 1', 'switch 2']],
	forcedOutcomes: hitDraws([40, 59], [15], [7]),
	features: ['ability.wonder-guard', 'hit.immunity-cause',
		'choice.switch'],
});

console.log('generated and legality-validated 6 Rollout/Ice Ball fixtures (40 boundaries)');
