#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'],
	{encoding: 'utf8'}).trim();
if (actual !== REVISION) throw new Error(`expected ${REVISION}, got ${actual}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const outputDir = path.join(__dirname, 'derived');
fs.mkdirSync(outputDir, {recursive: true});

function stats(speciesID, level) {
	const base = dex.species.get(speciesID).baseStats;
	// The exported sets leave IVs unspecified (31) and use one HP EV, whose
	// quarter contribution is zero. Showdown resolves these exact Gen 3 stats.
	const scaled = stat => Math.floor((2 * base[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	const level = options.level || 100;
	return {
		species, level, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species, level), status: null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP}),
	};
}

function teamText(team) {
	return team.map(set => {
		const species = dex.species.get(set.species);
		return `${species.name} (${set.gender})\nAbility: ${dex.abilities.get(set.ability).name}\n` +
			`Level: ${set.level}\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
			`Hardy Nature\n${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`;
	}).join('\n');
}

function writeCase(spec) {
	const files = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const imported = Teams.import(text);
		const errors = validator.validateTeam(imported);
		if (errors) throw new Error(`${spec.id} p${side + 1} is illegal:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, files[side]), text);
	}
	const value = {
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived', source_file: spec.source,
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: files[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: spec.features,
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng',
			...(spec.terminal ? ['terminal'] : [])],
		limits: {max_boundaries: spec.choices.length + 1, max_actions: spec.choices.length * 2},
	};
	const normalized = normalizeCase(value);
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`), `${JSON.stringify(normalized, null, 2)}\n`);
}

const tyrogue = () => member('tyrogue', 'guts', ['tackle']);
const smeargle = (moves, options = {}) => member('smeargle', 'owntempo', moves, options);

for (const spec of [
	{
		id: 'detect-protect-endure-shared-stall-success', seed: [1, 2, 3, 2],
		source: 'data/moves.ts',
		description: 'Detect, Protect, and Endure share one consecutive-use stall counter',
		teams: [[smeargle(['detect', 'protect', 'endure'], {initialHP: 20})], [tyrogue()]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 3', 'move 1']],
		forcedOutcomes: [
			{label: 'stall.success', occurrence: 1, range: 2, result: 0},
			{label: 'stall.success', occurrence: 2, range: 4, result: 0},
		],
		features: ['choice.move', 'condition.volatile', 'hit.protect',
			'lifecycle.condition-duration', 'prng.labeled', 'prng.stall',
			'state.canonical', 'volatile.protect', 'volatile.endure',
			'damage.endure'],
	},
	{
		id: 'detect-endure-shared-stall-failure', seed: [1, 2, 3, 1],
		source: 'data/mods/gen5/conditions.ts',
		description: 'Endure fails at the shared one-half stall gate after Detect',
		teams: [[smeargle(['detect', 'endure'], {initialHP: 20})], [tyrogue()]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
		forcedOutcomes: [{label: 'stall.success', occurrence: 1, range: 2, result: 1}],
		features: ['choice.move', 'condition.volatile', 'hit.protect',
			'lifecycle.condition-duration', 'lifecycle.faint', 'lifecycle.terminal',
			'prng.labeled', 'prng.stall', 'state.canonical', 'volatile.protect',
			'volatile.endure', 'damage.endure'],
		terminal: true,
	},
	{
		id: 'endure-fixed-move-damage', seed: [1, 2, 3, 7],
		source: 'data/moves.ts',
		description: 'Endure clamps lethal fixed move damage to current HP minus one',
		teams: [[smeargle(['endure'], {initialHP: 30})],
			[member('machop', 'guts', ['seismictoss'], {level: 37})]],
		choices: [['move 1', 'move 1']],
		features: ['choice.move', 'condition.volatile', 'damage.fixed-level',
			'damage.endure', 'hit.accuracy', 'prng.labeled', 'state.canonical',
			'volatile.endure'],
	},
	{
		id: 'endure-multihit-each-hit', seed: [1, 2, 3, 1],
		source: 'data/mods/gen3/scripts.ts',
		description: 'Endure applies the Damage relay independently to every lethal multihit strike',
		teams: [[smeargle(['endure'], {initialHP: 5})],
			[smeargle(['furyattack'], {level: 99, gender: 'F'})]],
		choices: [['move 1', 'move 1']],
		forcedOutcomes: [
			{label: 'move.accuracy', occurrence: 1, range: 100, result: 54},
			{label: 'move.multihit_count', occurrence: 1, range: 8, result: 0},
			{label: 'move.critical', occurrence: 1, range: 16, result: 8},
			{label: 'move.damage_roll', occurrence: 1, range: 16, result: 13},
			{label: 'move.critical', occurrence: 2, range: 16, result: 4},
			{label: 'move.damage_roll', occurrence: 2, range: 16, result: 15},
		],
		features: ['choice.move', 'condition.volatile', 'hit.accuracy', 'hit.multihit',
			'damage.endure', 'prng.labeled', 'prng.multihit', 'state.canonical',
			'volatile.endure'],
	},
]) writeCase(spec);

console.log('generated and legality-validated 4 protection fixtures');
