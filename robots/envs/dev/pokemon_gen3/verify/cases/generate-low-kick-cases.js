#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-low-kick-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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
	const ordinary = stat => 2 * base[stat] + 36;
	return [2 * base.hp + 141, ordinary('atk'), ordinary('def'),
		ordinary('spa'), ordinary('spd'), ordinary('spe')];
}

function member(species, ability, moves) {
	return {species, level: 100, gender: 'M', nature: 'hardy', ability,
		item: '', moves, stats: stats(species), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n') + '\n').join('\n');
}

function writeCase(target) {
	const id = `low-kick-${target.species}`;
	const teams = [[member('machop', 'guts', ['lowkick'])],
		[member(target.species, target.ability, [target.move])]];
	const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
	}
	const choices = [['move 1', 'move 1']];
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/moves.ts#lowkick.basePowerCallback; sim/pokemon.ts#getWeight',
			test_name: `Low Kick resolves ${target.power} power from ${target.weightkg}kg target`,
			oracle_revision: REVISION},
		format: 'gen3ou', seed: [41, 17, 29, 7],
		teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: choices, choices, forced_outcomes: [],
		features: ['choice.move', 'damage.gen3', 'formula.target-weight-power',
			'hit.accuracy', 'prng.labeled', 'state.canonical',
			...(target.immune ? ['hit.type-immunity'] : [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: 2, max_actions: 2},
	});
	fs.writeFileSync(path.join(outputDir, `${id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

for (const target of [
	{species: 'pikachu', ability: 'static', move: 'thunderbolt', weightkg: 6, power: 20},
	{species: 'magikarp', ability: 'swiftswim', move: 'splash', weightkg: 10, power: 40},
	{species: 'persian', ability: 'limber', move: 'scratch', weightkg: 32, power: 60},
	{species: 'skarmory', ability: 'keeneye', move: 'sandattack', weightkg: 50.5, power: 80},
	{species: 'slaking', ability: 'truant', move: 'scratch', weightkg: 130.5, power: 100},
	{species: 'snorlax', ability: 'immunity', move: 'tackle', weightkg: 460, power: 120},
	{species: 'gastly', ability: 'levitate', move: 'lick', weightkg: 0.1, power: 20, immune: true},
]) writeCase(target);

console.log('generated and legality-validated 7 Low Kick fixtures');
