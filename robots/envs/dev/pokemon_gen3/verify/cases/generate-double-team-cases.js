#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-double-team-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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

function member(species, ability, moves, gender) {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return {species, level: 100, gender, ability, item: '', moves,
		stats: [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
			scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5], status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
		'Hardy Nature\n' + set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n') +
		'\n').join('\n');
}

const id = 'metronome-double-team-evasion';
const teams = [
	[member('blissey', 'naturalcure', ['metronome', 'softboiled'], 'F')],
	[member('persian', 'limber', ['scratch', 'protect'], 'M')],
];
const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
for (let side = 0; side < 2; side++) {
	const text = teamText(teams[side]);
	const errors = validator.validateTeam(Teams.import(text));
	if (errors) throw new Error(`${id} p${side + 1}:\n${errors.join('\n')}`);
	fs.writeFileSync(path.join(outputDir, sources[side]), text);
}
const choices = [['move 1', 'move 2']];
const fixture = normalizeCase({
	schema: 'pokemon-native-differential-case-v1', id,
	provenance: {kind: 'showdown-derived',
		source_file: 'data/moves.ts#doubleteam; sim/battle-actions.ts',
		test_name: 'legal Metronome calls banned Double Team and applies its evasion boost',
		oracle_revision: REVISION},
	format: 'gen3ou', seed: [11, 4388, 11058, 25960],
	teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
	source_choices: choices, choices,
	forced_outcomes: [{label: 'move.delegation.selection', occurrence: 1,
		range: 336, result: 104}],
	features: ['choice.move', 'effect.boost', 'move.called-entry', 'hit.accuracy',
		'prng.labeled', 'state.canonical'],
	boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
	limits: {max_boundaries: 2, max_actions: 2},
});
fs.writeFileSync(path.join(outputDir, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
console.log('generated and legality-validated Double Team fixture');
