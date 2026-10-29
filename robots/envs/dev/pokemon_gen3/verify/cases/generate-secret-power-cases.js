#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdown = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-secret-power-cases.js SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdown, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim() !== REVISION) {
	throw new Error('wrong Showdown revision');
}
const {Dex, Teams, TeamValidator} = require(showdown);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

const stats = id => {
	const base = dex.species.get(id).baseStats;
	return [2 * base.hp + 141, 2 * base.atk + 36, 2 * base.def + 36,
		2 * base.spa + 36, 2 * base.spd + 36, 2 * base.spe + 36];
};
const member = (species, ability, moves) => ({species, level: 100, gender: 'M',
	ability, item: '', moves, stats: stats(species), status: null});
const text = team => team.map(set => `${dex.species.get(set.species).name} (M)\n` +
	`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\nEVs: 1 HP\nHardy Nature\n` +
	`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');

for (const [suffix, tail] of [['secondary-a', 1], ['secondary-b', 14]]) {
	const id = `secret-power-${suffix}`;
	const teams = [[member('smeargle', 'owntempo', ['secretpower'])],
		[member('blissey', 'naturalcure', ['pound'])]];
	const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const packed = text(teams[side]);
		const errors = validator.validateTeam(Teams.import(packed));
		if (errors) throw new Error(`${id}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(out, sources[side]), packed);
	}
	const choices = [['move 1', 'move 1']];
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/mods/gen4/moves.ts#secretpower; data/moves.ts#secretpower',
			test_name: 'Gen 3 terrain-free Secret Power ordinary paralysis secondary',
			oracle_revision: REVISION},
		format: 'gen3ou', seed: [313, 197, 83, tail],
		teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: choices, choices, forced_outcomes: [],
		features: ['choice.move', 'damage.gen3', 'effect.secondary',
			'prng.labeled', 'prng.secondary', 'status.paralysis', 'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: 2, max_actions: 2},
	});
	fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}
console.log('generated and legality-validated 2 Secret Power fixtures (4 boundaries)');
