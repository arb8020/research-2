#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate-lock-on-cases.js POKEMON_SHOWDOWN_DIR');
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

function member(species, ability, moves, options = {}) {
	const level = options.level || 100;
	return {species, level, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species, level), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: ${set.level}\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
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
		provenance: {kind: 'showdown-derived', source_file: spec.source,
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: files[side], normalized: team})),
		source_choices: spec.choices, choices: spec.nativeChoices || spec.choices,
		forced_outcomes: spec.forcedOutcomes || [], features: spec.features,
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1, max_actions: spec.choices.length * 2},
	};
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(normalizeCase(value), null, 2)}\n`);
}

const smeargle = (moves, options) => member('smeargle', 'owntempo', moves, options);
const common = ['choice.move', 'condition.volatile', 'handler.accuracy',
	'handler.invulnerability', 'hit.accuracy-bypass', 'lifecycle.condition-duration',
	'prng.labeled', 'state.canonical', 'volatile.lock-on'];

for (const spec of [
	{
		id: 'lock-on-alias-repeat-accuracy', seed: [1, 2, 3, 4],
		source: 'data/moves.ts',
		description: 'Lock-On and Mind Reader share duplicate rejection and accuracy bypass',
		teams: [[smeargle(['lockon', 'mindreader', 'toxic'])],
			[member('blissey', 'naturalcure', ['softboiled'])]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1'],
			['move 2', 'move 1'], ['move 2', 'move 1'],
			['move 1', 'move 1'], ['move 3', 'move 1']],
		features: common,
	},
	{
		id: 'lock-on-semi-invulnerable', seed: [2, 3, 4, 5],
		source: 'data/moves.ts',
		description: 'Lock-On bypasses Fly invulnerability and the follow-up accuracy draw',
		teams: [[smeargle(['lockon', 'toxic'])],
			[smeargle(['fly'], {level: 50, gender: 'F'})]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
		features: [...common, 'hit.invulnerability-bypass'],
	},
	{
		id: 'lock-on-protect-and-immunity', seed: [3, 4, 5, 6],
		source: 'data/moves.ts',
		description: 'Lock-On bypasses neither Protect nor natural type immunity',
		teams: [[smeargle(['lockon', 'toxic', 'earthquake'])],
			[member('skarmory', 'keeneye', ['rest', 'protect'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2'],
			['move 1', 'move 1'], ['move 3', 'move 1']],
		features: [...common, 'hit.protect', 'hit.type-immunity'],
	},
	{
		id: 'lock-on-switch-relations', seed: [4, 5, 6, 7],
		source: 'data/moves.ts',
		description: 'Owner switching clears Lock-On while target switching invalidates its identity relation',
		teams: [[smeargle(['lockon', 'toxic']), member('persian', 'limber', ['rest'])],
			[member('blissey', 'naturalcure', ['softboiled']),
				member('chansey', 'naturalcure', ['softboiled'], {gender: 'F'})]],
		choices: [['move 1', 'move 1'], ['switch 2', 'move 1'],
			['switch 2', 'move 1'], ['move 1', 'move 1'], ['move 2', 'switch 2']],
		nativeChoices: [['move 1', 'move 1'], ['switch 2', 'move 1'],
			['switch 1', 'move 1'], ['move 1', 'move 1'], ['move 2', 'switch 2']],
		features: [...common, 'choice.switch'],
	},
]) writeCase(spec);

console.log('generated and legality-validated 4 Lock-On fixtures');
