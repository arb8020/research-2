#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) {
	throw new Error('usage: node generate-destiny-bond-grudge-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
}
const showdownDir = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
const actual = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== REVISION) throw new Error(`expected ${REVISION}, got ${actual}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
fs.mkdirSync(outputDir, {recursive: true});

function stats(speciesID, level) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => Math.floor((2 * base[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, moves, level, ability, options = {}) {
	return {species, level, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species, level), status: options.status || null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP})};
}

function smeargle(moves, level, options) {
	return member('smeargle', moves, level, 'owntempo', options);
}

function fastSmeargle(moves, options) {
	const result = smeargle(moves, 100, options);
	result.stats[5] = 249;
	return result;
}

function blissey(moves) {
	return member('blissey', moves, 100, 'naturalcure', {gender: 'F'});
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: ${set.level}\n` +
		(set.stats[5] === stats(set.species, set.level)[5] ?
			`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` :
			`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 252 Spe\n`) +
		`Hardy Nature\n` +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

function writeCase(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
	}
	const value = {
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/moves.ts; sim/battle-actions.ts; sim/pokemon.ts',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'condition.volatile', 'handler.before-move',
			'handler.prepare-hit', 'lifecycle.faint',
			'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events',
			'prng', 'terminal'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	};
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(normalizeCase(value), null, 2)}\n`);
}

for (const spec of [
	{
		id: 'destiny-bond-direct-move-ko', seed: [101, 102, 103, 104],
		description: 'Destiny Bond faints the opposing source of a direct move KO',
		teams: [[smeargle(['destinybond', 'splash'], 50, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash', 'quickattack'], 100)]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	},
	{
		id: 'destiny-bond-before-move-cleanup', seed: [111, 112, 113, 114],
		description: 'Destiny Bond is removed before its user attempts another move',
		teams: [[smeargle(['destinybond', 'splash'], 100, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash', 'swift'], 50)]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	},
	{
		id: 'destiny-bond-consecutive-refresh', seed: [121, 122, 123, 124],
		description: 'Consecutive Destiny Bond refreshes the volatile and remains effective',
		teams: [[smeargle(['destinybond', 'splash'], 50, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash', 'quickattack'], 100)]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1'],
			['move 2', 'move 2']],
	},
	{
		id: 'grudge-direct-move-ko', seed: [131, 132, 133, 134],
		description: 'Grudge zeros every slot matching the direct KO move',
		teams: [[smeargle(['grudge', 'splash'], 50, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash', 'quickattack'], 100)]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	},
	{
		id: 'grudge-before-move-cleanup', seed: [141, 142, 143, 144],
		description: 'Grudge is removed before its user attempts another move',
		teams: [[smeargle(['grudge', 'splash'], 100, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash', 'swift'], 50)]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	},
	{
		id: 'grudge-source-fainted-exclusion', seed: [151, 152, 153, 154],
		description: 'Grudge does not erase PP when the direct KO move also faints its source',
		teams: [[smeargle(['grudge', 'splash'], 50, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash', 'selfdestruct'], 100),
			member('magikarp', ['splash'], 50, 'swiftswim')]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	},
	{
		id: 'destiny-bond-future-sight-exclusion', seed: [161, 162, 163, 164],
		description: 'Destiny Bond ignores a delayed Future Sight KO',
		teams: [[smeargle(['splash', 'destinybond'], 100, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['futuresight', 'splash'], 50)]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 2', 'move 2']],
	},
	{
		id: 'grudge-doom-desire-exclusion', seed: [171, 172, 173, 174],
		description: 'Grudge ignores a delayed Doom Desire KO',
		teams: [[smeargle(['splash', 'grudge'], 100, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['doomdesire', 'splash'], 50)]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 2', 'move 2']],
	},
	{
		id: 'destiny-bond-doom-desire-exclusion', seed: [175, 176, 177, 178],
		description: 'Destiny Bond ignores a delayed Doom Desire KO',
		teams: [[smeargle(['splash', 'destinybond'], 100, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['doomdesire', 'splash'], 50)]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 2', 'move 2']],
	},
	{
		id: 'grudge-future-sight-exclusion', seed: [179, 180, 181, 182],
		description: 'Grudge ignores a delayed Future Sight KO',
		teams: [[smeargle(['splash', 'grudge'], 100, {initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['futuresight', 'splash'], 50)]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 2', 'move 2']],
	},
	{
		id: 'destiny-bond-indirect-faint-exclusion', seed: [181, 182, 183, 184],
		description: 'Destiny Bond ignores an indirect burn faint',
		teams: [[smeargle(['destinybond'], 100, {status: 'brn', initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'grudge-indirect-faint-exclusion', seed: [191, 192, 193, 194],
		description: 'Grudge ignores an indirect burn faint',
		teams: [[smeargle(['grudge'], 100, {status: 'brn', initialHP: 1}),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[smeargle(['splash'], 50)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'destiny-bond-move-aborted-cleanup', seed: [1, 23, 47, 71],
		description: 'A fully paralyzed attempted move removes Destiny Bond through MoveAborted',
		teams: [[fastSmeargle(['destinybond', 'splash']),
			member('magikarp', ['splash'], 50, 'swiftswim')],
		[blissey(['thunderwave', 'softboiled'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
		forcedOutcomes: [{label: 'status.paralysis.before_move', occurrence: 1,
			range: 4, result: 0}],
	},
]) writeCase(spec);

console.log('generated and legality-validated 13 Destiny Bond / Grudge fixtures');
