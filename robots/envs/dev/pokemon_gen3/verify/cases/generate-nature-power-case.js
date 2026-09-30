#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) {
	throw new Error('usage: node generate-nature-power-case.js POKEMON_SHOWDOWN_DIR');
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
function member(species, ability, moves, gender) {
	return {species, level: 100, gender, nature: 'hardy', ability, item: '',
		moves, stats: stats(species), status: null};
}
function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

const id = 'nature-power-fixed-swift-protect';
const teams = [
	[member('smeargle', 'owntempo', ['naturepower'], 'M')],
	[member('persian', 'limber', ['scratch', 'protect'], 'F')],
];
const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
teams.forEach((team, side) => {
	const text = teamText(team);
	const errors = validator.validateTeam(Teams.import(text));
	if (errors) throw new Error(`${id} p${side + 1}: ${errors.join('; ')}`);
	fs.writeFileSync(path.join(output, sources[side]), text);
});
const choices = [['move 1', 'move 1'], ['move 1', 'move 2']];
const fixture = normalizeCase({
	schema: 'pokemon-native-differential-case-v1', id,
	provenance: {kind: 'showdown-derived', source_file: 'data/mods/gen3/moves.ts',
		test_name: 'Nature Power deterministically calls Swift; the child independently reaches Protect',
		oracle_revision: REVISION},
	format: 'gen3ou', seed: [419, 71, 29, 7],
	teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
	source_choices: choices, choices, forced_outcomes: [],
	features: ['choice.move', 'hit.protect', 'move.called-entry',
		'move.fixed-delegation', 'prng.labeled', 'state.canonical'],
	boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
	limits: {max_boundaries: 3, max_actions: 4},
});
fs.writeFileSync(path.join(output, `${id}.json`),
	`${JSON.stringify(fixture, null, 2)}\n`);
console.log(`generated and legality-validated ${id}`);
