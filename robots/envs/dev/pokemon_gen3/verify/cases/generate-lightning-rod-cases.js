#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdown = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-lightning-rod-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdown, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim() !== revision) {
	throw new Error('wrong revision');
}
const {Dex, Teams, TeamValidator} = require(showdown);
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const output = path.join(__dirname, 'derived');
function stats(id) {
	const base = dex.species.get(id).baseStats;
	const stat = key => 2 * base[key] + 31;
	return [stat('hp') + 110, stat('atk') + 5, stat('def') + 5,
		stat('spa') + 5, stat('spd') + 5, stat('spe') + 5];
}
function mon(species, ability, move) {
	return {species, level: 100, gender: 'M', nature: 'hardy', ability,
		item: '', moves: [move], stats: stats(species), status: null};
}
function text(pokemon) {
	return `${dex.species.get(pokemon.species).name} (M)\n` +
		`Ability: ${dex.abilities.get(pokemon.ability).name}\nLevel: 100\n` +
		`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
		`- ${dex.moves.get(pokemon.moves[0]).name}\n`;
}
function emit(id, attack) {
	const teams = [[mon('smeargle', 'owntempo', attack)],
		[mon('marowak', 'lightningrod', 'doubleedge')]];
	const files = [`${id}-p1.txt`, `${id}-p2.txt`];
	teams.forEach((team, side) => {
		const body = text(team[0]);
		const errors = validator.validateTeam(Teams.import(body));
		if (errors) throw new Error(errors.join('; '));
		fs.writeFileSync(path.join(output, files[side]), body);
	});
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id,
		provenance: {kind: 'showdown-derived', source_file: 'data/mods/gen3/abilities.ts',
			test_name: `Lightning Rod singles target identity: ${attack}`, oracle_revision: revision},
		format: 'gen3ou', seed: [431, 79, 37, 13],
		teams: teams.map((team, side) => ({source: files[side], normalized: team})),
		source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
		forced_outcomes: [],
		features: ['ability.lightning-rod', 'choice.move', 'damage.gen3',
			'hit.accuracy', 'prng.labeled', 'state.canonical', 'target.singles-normalization'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: 2, max_actions: 2},
	});
	fs.writeFileSync(path.join(output, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}
emit('lightning-rod-electric-single-target', 'thunderbolt');
emit('lightning-rod-nonelectric-single-target', 'psychic');
console.log('generated 2 Lightning Rod singles cases');
