#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdown = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-follow-me-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdown, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim() !== revision) {
	throw new Error('wrong revision');
}
const {Dex, Teams, TeamValidator} = require(showdown);
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const output = path.join(__dirname, 'derived');

function stats(speciesID) {
	const base = dex.species.get(speciesID).baseStats;
	const stat = id => 2 * base[id] + 31;
	return [stat('hp') + 110, stat('atk') + 5, stat('def') + 5,
		stat('spa') + 5, stat('spd') + 5, stat('spe') + 5];
}
function member(species, ability, move) {
	return {species, level: 100, gender: 'M', nature: 'hardy', ability,
		item: '', moves: [move], stats: stats(species), status: null};
}
function teamText(pokemon) {
	return `${dex.species.get(pokemon.species).name} (M)\n` +
		`Ability: ${dex.abilities.get(pokemon.ability).name}\nLevel: 100\n` +
		`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
		`- ${dex.moves.get(pokemon.moves[0]).name}\n`;
}

const id = 'follow-me-singles-try-rejection';
const teams = [[member('smeargle', 'owntempo', 'followme')],
	[member('magikarp', 'swiftswim', 'splash')]];
const files = [`${id}-p1.txt`, `${id}-p2.txt`];
teams.forEach((team, side) => {
	const text = teamText(team[0]);
	const errors = validator.validateTeam(Teams.import(text));
	if (errors) throw new Error(errors.join('; '));
	fs.writeFileSync(path.join(output, files[side]), text);
});
const fixture = normalizeCase({
	schema: 'pokemon-native-differential-case-v1',
	id,
	provenance: {kind: 'showdown-derived', source_file: 'data/moves.ts',
		test_name: 'Follow Me rejects after PP deduction in singles', oracle_revision: revision},
	format: 'gen3ou', seed: [421, 73, 31, 11],
	teams: teams.map((team, side) => ({source: files[side], normalized: team})),
	source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
	forced_outcomes: [],
	features: ['choice.move', 'handler.try', 'prng.labeled', 'state.canonical'],
	boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
	limits: {max_boundaries: 2, max_actions: 2},
});
fs.writeFileSync(path.join(output, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
console.log(`generated ${id}`);
