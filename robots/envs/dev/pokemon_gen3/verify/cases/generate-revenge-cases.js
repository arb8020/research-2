#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-revenge-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
const showdownDir = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
const revision = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected ${REVISION}, got ${revision}`);
const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
fs.mkdirSync(outputDir, {recursive: true});

function stats(species) {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, gender = 'M') {
	return {species, level: 100, gender, ability, item: '', moves,
		stats: stats(species), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n') + '\n').join('\n');
}

function writeCase(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/moves.ts#revenge; sim/pokemon.ts#attackedBy',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed || [41, 17, 29, 7],
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: [],
		features: ['choice.move', 'handler.base-power', 'provenance.attacked-by',
			'prng.labeled', 'state.canonical', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = moves => member('smeargle', 'owntempo', moves);
for (const spec of [
	{id: 'revenge-no-history', description: 'Revenge remains 60 power without qualifying damage',
		teams: [[smeargle(['revenge'])], [smeargle(['splash'])]],
		choices: [['move 1', 'move 1']]},
	{id: 'revenge-same-turn-damage', description: 'positive same-turn damage from the target doubles Revenge',
		teams: [[smeargle(['revenge'])], [smeargle(['tackle'])]],
		choices: [['move 1', 'move 1']]},
	{id: 'revenge-fixed-damage', description: 'numeric fixed damage is category-agnostic and doubles Revenge',
		teams: [[smeargle(['revenge'])], [smeargle(['dragonrage'])]],
		choices: [['move 1', 'move 1']]},
	{id: 'revenge-substitute-zero-damage', description: 'Substitute interception records no qualifying HP damage',
		teams: [[smeargle(['substitute', 'revenge'])], [smeargle(['splash', 'tackle'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
		features: ['volatile.substitute']},
	{id: 'revenge-stale-damage', description: 'damage from a previous turn does not double Revenge',
		teams: [[smeargle(['splash', 'revenge'])], [smeargle(['tackle', 'splash'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']]},
	{id: 'revenge-replacement-target', description: 'switching changes the resolved target and rejects stale source identity',
		teams: [[smeargle(['revenge'])],
			[smeargle(['tackle']), member('magikarp', 'swiftswim', ['splash'])]],
		choices: [['move 1', 'move 1'], ['move 1', 'switch 2']],
		features: ['choice.switch', 'lifecycle.switch-persistence']},
]) writeCase(spec);

console.log('generated and legality-validated 6 Revenge fixtures');
