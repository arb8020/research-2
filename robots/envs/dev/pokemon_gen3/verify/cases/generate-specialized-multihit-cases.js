#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) {
	throw new Error('usage: generate-specialized-multihit-cases.js POKEMON_SHOWDOWN_DIR');
}
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {
	encoding: 'utf8',
}).trim() !== REVISION) throw new Error('wrong Showdown revision');

const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species) {
	const base = dex.species.get(species).baseStats;
	const stat = name => 2 * base[name] + 31;
	return [stat('hp') + 110, stat('atk') + 5, stat('def') + 5,
		stat('spa') + 5, stat('spd') + 5, stat('spe') + 5];
}

function member(species, ability, moves) {
	return {species, level: 100, gender: 'M', ability, item: '', moves,
		stats: stats(species), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP\nHardy Nature\n' +
		`${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`)
		.join('\n');
}

function emit(id, description, seed, p1, p2) {
	const choices = [['move 1', 'move 1']];
	const teams = [[p1], [p2]];
	const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(out, sources[side]), text);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'sim/battle-actions.ts#hitStepMoveHitLoop; data/moves.ts#triplekick,twineedle',
			test_name: description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed, teams: teams.map((team, side) => ({
			source: sources[side], normalized: team,
		})), source_choices: choices, choices, forced_outcomes: [],
		features: ['choice.move', 'damage.gen3', 'hit.multihit',
			'prng.labeled', 'prng.secondary', 'status.poison',
			'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: 2, max_actions: 2},
	});
	fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = moves => member('smeargle', 'owntempo', moves);
const blissey = member('blissey', 'naturalcure', ['pound']);
emit('triple-kick-per-hit-complete', 'Triple Kick resolves accuracy and indexed power per hit',
	[301, 41, 17, 9], smeargle(['triplekick']), blissey);
emit('triple-kick-per-hit-stop', 'a later Triple Kick accuracy failure stops without a move-level miss',
	[302, 41, 17, 9], smeargle(['triplekick']), blissey);
emit('twineedle-per-hit-poison', 'Twineedle owns an independent poison secondary after each hit',
	[303, 41, 17, 9], smeargle(['twineedle']), blissey);
emit('twineedle-poison-immunity', 'Twineedle retains per-hit secondary staging against a Poison-immune target',
	[304, 41, 17, 9], smeargle(['twineedle']), member('skarmory', 'keeneye', ['peck']));

console.log('generated and legality-validated 4 specialized multihit fixtures (8 boundaries)');
