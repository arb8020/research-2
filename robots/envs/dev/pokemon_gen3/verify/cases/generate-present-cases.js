#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdown = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-present-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdown, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim() !== REVISION) {
	throw new Error('wrong Showdown revision');
}

const {Dex, Teams, TeamValidator} = require(showdown);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species) {
	const base = dex.species.get(species).baseStats;
	return [2 * base.hp + 141, 2 * base.atk + 36, 2 * base.def + 36,
		2 * base.spa + 36, 2 * base.spd + 36, 2 * base.spe + 36];
}

function member(species, ability, moves, options = {}) {
	return {
		species, level: 100, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species), status: null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP}),
	};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\nEVs: 1 HP\nHardy Nature\n` +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

function write(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(out, sources[side]), text);
	}
	const choices = spec.choices || [['move 1', 'move 1']];
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/moves.ts#present; sim/battle-actions.ts',
			test_name: spec.test,
			oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: [217, 90, 15, spec.seedTail],
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: choices, choices,
		forced_outcomes: spec.forced,
		features: spec.features,
		boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity', 'state', 'events', 'prng'],
		limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${spec.id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = (moves, options) => member('smeargle', 'owntempo', moves, options);
const ordinaryTarget = () => smeargle(['splash'], {gender: 'F'});
const roll = result => ({label: 'move.resolution_variant', occurrence: 1, range: 10, result});
const accuracy = result => ({label: 'move.accuracy', occurrence: 1, range: 100, result});
const combatRolls = (critical, damage) => [
	{label: 'move.critical', occurrence: 1, range: 16, result: critical},
	{label: 'move.damage_roll', occurrence: 1, range: 16, result: damage},
];
const common = ['choice.move', 'prng.labeled', 'state.canonical'];
const damageFeatures = [...common, 'damage.gen3', 'damage.variable-power', 'hit.accuracy', 'hit.resolved-power'];

for (const [power, result, seedTail, accuracyResult, critical, damage] of [
	[40, 3, 1, 34, 0, 9],
	[80, 6, 2, 42, 8, 15],
	[120, 9, 25, 16, 14, 12],
]) {
	write({
		id: `present-damage-${power}`, seedTail,
		test: `Present selects its ${power}-power weighted damage branch`,
		teams: [[smeargle(['present'])], [ordinaryTarget()]],
		forced: [roll(result), accuracy(accuracyResult), ...combatRolls(critical, damage)],
		features: damageFeatures,
	});
}

write({
	id: 'present-weighted-heal', seedTail: 10,
	test: 'Present selects its two-in-ten quarter-heal branch',
	teams: [[smeargle(['present'])], [smeargle(['splash'], {gender: 'F', initialHP: 100})]],
	forced: [roll(0), accuracy(47)],
	features: [...common, 'effect.heal', 'hit.accuracy'],
});

write({
	id: 'present-accuracy-miss', seedTail: 9,
	test: 'Present selects a damage branch before failing its accuracy check',
	teams: [[smeargle(['present'])], [ordinaryTarget()]],
	forced: [roll(8), accuracy(95)], features: damageFeatures,
});

write({
	id: 'present-ghost-immunity', seedTail: 11,
	test: 'A damaging Present branch is stopped by Normal type immunity',
	teams: [[smeargle(['present'])], [member('banette', 'insomnia', ['nightmare'], {gender: 'F'})]],
	forced: [roll(8), accuracy(58)],
	features: [...damageFeatures, 'hit.immunity-cause', 'hit.type-immunity'],
});

write({
	id: 'present-protect', seedTail: 12,
	test: 'Protect blocks a damaging Present branch',
	teams: [[smeargle(['present'])], [smeargle(['protect'], {gender: 'F'})]],
	forced: [roll(7), accuracy(17)],
	features: [...damageFeatures, 'hit.protect', 'volatile.protect'],
});

write({
	id: 'present-heal-substitute-blocked', seedTail: 14,
	test: 'Gen 3 Substitute blocks Present healing despite the resolved infiltrates flag',
	teams: [[smeargle(['present'])],
		[member('persian', 'limber', ['substitute'], {gender: 'F', initialHP: 200})]],
	forced: [roll(1), accuracy(17)],
	features: [...common, 'effect.heal', 'hit.accuracy', 'hit.substitute', 'volatile.substitute'],
});

write({
	id: 'present-damage-substitute', seedTail: 0,
	test: 'Present damage is absorbed by an existing Substitute',
	teams: [[smeargle(['present'])],
		[member('persian', 'limber', ['substitute'], {gender: 'F', initialHP: 200})]],
	forced: [roll(8), accuracy(41), ...combatRolls(13, 1)],
	features: [...damageFeatures, 'hit.substitute', 'volatile.substitute'],
});

write({
	id: 'present-heal-full-hp-failure', seedTail: 10,
	test: 'Present healing fails against a full-HP target',
	teams: [[smeargle(['present'])], [ordinaryTarget()]],
	forced: [roll(0), accuracy(47)], features: [...common, 'effect.heal', 'hit.accuracy'],
});

console.log('generated and legality-validated 10 Present fixtures (20 boundaries)');
