#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate-hidden-power-cases.js POKEMON_SHOWDOWN_DIR');
const outputDir = path.join(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const actual = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`wrong revision ${actual}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const statNames = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
const perfect = {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31};
const dark30 = {hp: 29, atk: 29, def: 29, spa: 29, spd: 29, spe: 29};
const ground70 = {hp: 30, atk: 30, def: 30, spa: 31, spd: 30, spe: 30};
const electric70 = {hp: 30, atk: 30, def: 30, spa: 31, spd: 31, spe: 30};

function stats(speciesID, level, ivs) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => Math.floor((2 * base[stat] + ivs[stat]) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, moves, level, ability, ivs = perfect) {
	return {species, level, gender: 'M', ability, item: '', moves,
		stats: stats(species, level, ivs), ivs: statNames.map(stat => ivs[stat]), status: null};
}

function teamText(team) {
	return team.map(set => {
		const ivs = Object.fromEntries(statNames.map((stat, index) => [stat, set.ivs[index]]));
		const moves = set.moves.map(id => id === 'hiddenpower' ?
			`Hidden Power [${dex.getHiddenPower(ivs).type}]` : dex.moves.get(id).name);
		return `${dex.species.get(set.species).name} (${set.gender})\n` +
			`Ability: ${dex.abilities.get(set.ability).name}\nLevel: ${set.level}\n` +
			`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
			`IVs: ${set.ivs[0]} HP / ${set.ivs[1]} Atk / ${set.ivs[2]} Def / ${set.ivs[3]} SpA / ${set.ivs[4]} SpD / ${set.ivs[5]} Spe\n` +
			`Hardy Nature\n${moves.map(name => `- ${name}`).join('\n')}\n`;
	}).join('\n');
}

function writeCase(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const source = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(source));
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), source);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'sim/dex.ts; sim/pokemon.ts; data/mods/gen3/moves.ts',
			test_name: spec.description, oracle_revision: revision},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'damage.gen3', 'damage.variable-power', 'prng.labeled', 'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1, max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

const passive = (species = 'smeargle', level = 100, ability = 'owntempo', move = 'splash') =>
	member(species, [move], level, ability);
const cases = [
	{id: 'hidden-power-dark70-special-effective', seed: [101, 102, 103, 104],
		description: 'all-31 IVs construct 70-power Dark special Hidden Power and hit Psychic effectively',
		teams: [[member('smeargle', ['hiddenpower'], 100, 'owntempo')], [passive('slowpoke', 100, 'owntempo', 'calmmind')]], choices: [['move 1', 'move 1']]},
	{id: 'hidden-power-dark30-power-floor', seed: [105, 106, 107, 108],
		description: 'all-29 IVs preserve Dark type while constructing the minimum 30 base power',
		teams: [[member('smeargle', ['hiddenpower'], 100, 'owntempo', dark30)], [passive()]], choices: [['move 1', 'move 1']]},
	{id: 'hidden-power-ground70-physical-stab-effective', seed: [109, 110, 111, 112],
		description: 'mixed IV bits construct 70-power Ground physical Hidden Power; Golem receives STAB and hits Magneton fourfold',
		teams: [[member('golem', ['hiddenpower'], 100, 'rockhead', ground70)], [passive('magneton', 100, 'magnetpull', 'metalsound')]], choices: [['move 1', 'move 1']]},
	{id: 'hidden-power-counter-special-type', seed: [113, 114, 115, 116],
		description: 'Counter captures Hidden Power by move identity even when its constructed Dark type makes its category Special',
		teams: [[member('smeargle', ['hiddenpower'], 100, 'owntempo')], [member('smeargle', ['counter'], 50, 'owntempo')]], choices: [['move 1', 'move 1']]},
	{id: 'hidden-power-mirror-coat-rejects', seed: [117, 118, 119, 120],
		description: 'Mirror Coat rejects Hidden Power by move identity even when its constructed category is Special',
		teams: [[member('smeargle', ['hiddenpower'], 100, 'owntempo')], [member('smeargle', ['mirrorcoat'], 50, 'owntempo')]], choices: [['move 1', 'move 1']]},
	{id: 'hidden-power-electric-ground-immunity', seed: [121, 122, 123, 124],
		description: 'mixed IV bits construct Electric Hidden Power and the dynamic type observes Ground immunity',
		teams: [[member('smeargle', ['hiddenpower'], 100, 'owntempo', electric70)], [passive('golem', 100, 'rockhead', 'earthquake')]], choices: [['move 1', 'move 1']]},
];

for (const spec of cases) writeCase(spec);
process.stdout.write(`generated ${cases.length} legal Hidden Power fixtures in ${outputDir}\n`);
