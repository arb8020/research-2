#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) {
	throw new Error('usage: node generate-retaliation-cases.js POKEMON_SHOWDOWN_DIR');
}
const actual = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
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
	const scaled = stat => Math.floor((2 * base[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, moves, level, ability, options = {}) {
	return {species, level, gender: options.gender || 'M', ability, item: '',
		moves, stats: stats(species, level), status: null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP})};
}

function smeargle(moves, level, options) {
	return member('smeargle', moves, level, 'owntempo', options);
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\n` +
		`Level: ${set.level}\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
		`Hardy Nature\n${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`)
		.join('\n');
}

function writeCase(spec) {
	const files = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, files[side]), text);
	}
	const value = {
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/moves.ts; data/mods/gen3/moves.ts',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: files[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'condition.volatile', 'damage.fixed-literal',
			'handler.damage', 'handler.try', 'prng.labeled', 'state.canonical'],
		boundaries: spec.boundaries ||
			['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	};
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(normalizeCase(value), null, 2)}\n`);
}

for (const spec of [
	{
		id: 'retaliation-counter-fixed-physical', seed: [11, 12, 13, 14],
		description: 'Counter captures physical fixed damage and returns twice its value',
		teams: [[smeargle(['sonicboom'], 100)], [smeargle(['counter'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'retaliation-mirror-coat-fixed-special', seed: [21, 22, 23, 24],
		description: 'Mirror Coat captures special fixed damage and returns twice its value',
		teams: [[smeargle(['dragonrage'], 100)], [smeargle(['mirrorcoat'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'retaliation-wrong-class-failure', seed: [31, 32, 33, 34],
		description: 'Counter does not capture special damage and Mirror Coat does not capture physical damage',
		teams: [[smeargle(['dragonrage', 'sonicboom'], 100)],
			[smeargle(['counter', 'mirrorcoat'], 50)]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	},
	{
		id: 'retaliation-miss-no-history', seed: [1, 2, 3, 7],
		description: 'A missed physical move leaves Counter without damage history',
		teams: [[smeargle(['megapunch'], 100)], [smeargle(['counter'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'retaliation-substitute-no-history', seed: [1, 2, 3, 4],
		description: 'Damage absorbed by Substitute does not feed Counter',
		teams: [[smeargle(['splash', 'sonicboom'], 100)],
			[member('machop', ['substitute', 'counter'], 50, 'guts')]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	},
	{
		id: 'retaliation-multihit-last-hit', seed: [1, 2, 3, 1],
		description: 'Counter captures the last qualifying hit of a multihit move',
		teams: [[smeargle(['doublekick'], 100)], [smeargle(['counter'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'retaliation-response-type-immunity', seed: [41, 42, 43, 44],
		description: 'Counter captures damage but its Fighting response remains type-immune',
		teams: [[member('gengar', ['seismictoss'], 100, 'levitate')],
			[smeargle(['counter'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'retaliation-incoming-type-immunity', seed: [45, 46, 47, 48],
		description: 'An immune incoming move never reaches the retaliation Damage handler',
		teams: [[smeargle(['shadowball'], 100)],
			[smeargle(['mirrorcoat'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'retaliation-source-faint-cancels-action', seed: [51, 52, 53, 54],
		description: 'Gen 3 pre-resolution source self-faint cancels the queued Counter before forced replacement',
		teams: [[smeargle(['selfdestruct'], 5),
			member('magikarp', ['splash'], 100, 'swiftswim')],
			[smeargle(['counter'], 100)]],
		choices: [['move 1', 'move 1'], ['switch 2', null]],
	},
	{
		id: 'retaliation-weather-ball-clear-counter', seed: [61, 62, 63, 64],
		description: 'Clear-weather Weather Ball is physical and feeds Counter',
		teams: [[smeargle(['weatherball'], 100)],
			[smeargle(['counter'], 50)]],
		choices: [['move 1', 'move 1']],
		boundaries: ['request', 'choice', 'queue', 'state', 'events', 'prng'],
	},
	{
		id: 'retaliation-weather-ball-clear-mirror-coat', seed: [65, 66, 67, 68],
		description: 'Clear-weather Weather Ball is physical and does not feed Mirror Coat',
		teams: [[smeargle(['weatherball'], 100)],
			[smeargle(['mirrorcoat'], 50)]],
		choices: [['move 1', 'move 1']],
		boundaries: ['request', 'choice', 'queue', 'state', 'events', 'prng'],
	},
	{
		id: 'retaliation-weather-ball-rain-counter', seed: [69, 70, 71, 72],
		description: 'Rain-mutated Weather Ball is special and does not feed Counter',
		teams: [[smeargle(['weatherball', 'splash'], 100)],
			[member('blastoise', ['counter', 'raindance'], 50, 'torrent')]],
		choices: [['move 2', 'move 2'], ['move 1', 'move 1']],
		boundaries: ['request', 'choice', 'queue', 'state', 'events', 'prng'],
	},
	{
		id: 'retaliation-weather-ball-rain-mirror-coat', seed: [73, 74, 75, 76],
		description: 'Rain-mutated Weather Ball is special and feeds Mirror Coat',
		teams: [[smeargle(['weatherball', 'splash'], 100)],
			[member('blastoise', ['mirrorcoat', 'raindance'], 50, 'torrent')]],
		choices: [['move 2', 'move 2'], ['move 1', 'move 1']],
		boundaries: ['request', 'choice', 'queue', 'state', 'events', 'prng'],
	},
	{
		id: 'retaliation-delayed-future-sight-provenance', seed: [81, 82, 83, 84],
		description: 'Future Sight expiry is a Special Move Damage event after Mirror Coat has already acted',
		teams: [[smeargle(['futuresight', 'splash'], 100)],
			[smeargle(['mirrorcoat', 'splash'], 50)]],
		choices: [
			['move 1', 'move 2'], ['move 2', 'move 2'], ['move 2', 'move 1'],
		],
	},
	{
		id: 'retaliation-overkill-requested-damage', seed: [85, 86, 87, 88],
		description: 'Counter observes requested damage before HP capping even when its holder faints',
		teams: [[smeargle(['sonicboom'], 100)], [
			smeargle(['counter'], 50, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim'),
		]],
		choices: [['move 1', 'move 1'], [null, 'switch 2']],
	},
]) writeCase(spec);

console.log('generated and legality-validated 15 retaliation fixtures');
