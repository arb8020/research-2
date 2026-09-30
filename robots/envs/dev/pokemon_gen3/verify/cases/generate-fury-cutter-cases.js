#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-fury-cutter-cases.js POKEMON_SHOWDOWN_DIR');
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
	return [species === 'shedinja' ? 1 : scaled('hp') + 110,
		scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, gender = 'M') {
	return {species, level: 100, gender, ability, item: '', moves,
		stats: stats(species), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name}${
		set.gender === 'N' ? '' : ` (${set.gender})`}\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		`EVs: 1 HP\nHardy Nature\n` +
		`${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`)
		.join('\n');
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
			source_file: 'data/moves.ts#furycutter; data/mods/gen4/moves.ts#furycutter; data/mods/gen3/moves.ts#furycutter; test/sim/moves/furycutter.js',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed || [419, 71, 29, 7],
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes,
		features: ['choice.move', 'condition.volatile', 'handler.base-power',
			'handler.damaging-hit', 'handler.try-add-volatile',
			'lifecycle.condition-duration', 'prng.labeled',
			'state.canonical', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity',
			'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = moves => member('smeargle', 'owntempo', moves);
const blissey = moves => member('blissey', 'naturalcure', moves, 'F');

emit({
	id: 'fury-cutter-ramp-cap',
	description: 'six connected hits ramp 10, 20, 40, 80, 160, 160',
	teams: [[smeargle(['furycutter'])], [blissey(['softboiled'])]],
	choices: Array.from({length: 6}, () => ['move 1', 'move 1']),
	forcedOutcomes: [],
});

emit({
	id: 'fury-cutter-miss-expires',
	seed: [419, 71, 29, 3],
	description: 'a miss does not refresh the ramp and the following hit restarts at 10',
	teams: [[smeargle(['furycutter'])], [blissey(['softboiled'])]],
	choices: Array.from({length: 3}, () => ['move 1', 'move 1']),
	forcedOutcomes: [
		{label: 'move.accuracy', occurrence: 1, range: 100, result: 13},
		{label: 'move.accuracy', occurrence: 2, range: 100, result: 97},
		{label: 'move.accuracy', occurrence: 3, range: 100, result: 37},
		{label: 'move.critical', occurrence: 1, range: 16, result: 11},
		{label: 'move.critical', occurrence: 2, range: 16, result: 1},
		{label: 'move.damage_roll', occurrence: 1, range: 16, result: 11},
		{label: 'move.damage_roll', occurrence: 2, range: 16, result: 8},
	],
});

emit({
	id: 'fury-cutter-protect-expires',
	description: 'Protect blocks before accuracy and does not refresh the ramp',
	teams: [[smeargle(['furycutter'])], [blissey(['softboiled', 'protect'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 1', 'move 1']],
	forcedOutcomes: [], features: ['volatile.protect'],
});

emit({
	id: 'fury-cutter-wonder-guard-expires',
	description: 'Wonder Guard immunity does not refresh and expires the attacker ramp',
	teams: [[smeargle(['furycutter'])], [blissey(['softboiled']),
		member('shedinja', 'wonderguard', ['protect'], 'N')]],
	choices: [['move 1', 'move 1'], ['move 1', 'switch 2']],
	forcedOutcomes: [],
	features: ['choice.switch', 'ability.wonder-guard', 'hit.immunity-cause'],
});

emit({
	id: 'fury-cutter-source-switch-reset',
	description: 'switching the attacker clears its Fury Cutter ramp immediately',
	teams: [[smeargle(['furycutter']), member('magikarp', 'swiftswim', ['splash'])],
		[blissey(['softboiled'])]],
	choices: [['move 1', 'move 1'], ['switch 2', 'move 1']],
	forcedOutcomes: [],
	features: ['choice.switch', 'lifecycle.switch-persistence'],
});

console.log('generated and legality-validated 5 Fury Cutter fixtures');
