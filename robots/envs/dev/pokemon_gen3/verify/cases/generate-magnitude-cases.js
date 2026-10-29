#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const display = new Map([
	['smeargle', 'Smeargle'], ['blissey', 'Blissey'],
	['owntempo', 'Own Tempo'], ['naturalcure', 'Natural Cure'],
	['magnitude', 'Magnitude'], ['splash', 'Splash'], ['dig', 'Dig'],
	['softboiled', 'Soft-Boiled'],
]);
const name = id => display.get(id) || `${id[0].toUpperCase()}${id.slice(1)}`;
const pokemon = (species, ability, moves, stats) => ({
	species, level: 100, gender: 'M', ability, item: '', moves, stats, status: null,
});
const smeargle = moves => pokemon(
	'smeargle', 'owntempo', moves, [251, 76, 106, 76, 126, 186]);
const blissey = moves => pokemon(
	'blissey', 'naturalcure', moves, [651, 56, 56, 186, 306, 146]);

function writeTeam(filename, members) {
	const text = members.map(member =>
		`${name(member.species)} (M)\nAbility: ${name(member.ability)}\n` +
		`Level: 100\nHardy Nature\n${member.moves.map(move => `- ${name(move)}`).join('\n')}\n`
	).join('\n');
	fs.writeFileSync(path.join(out, filename), text);
}

function writeCase({id, seed, left, right, choices}) {
	const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
	writeTeam(sources[0], left);
	writeTeam(sources[1], right);
	const fixture = {
		schema: 'pokemon-native-differential-case-v1', id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/moves.ts:10884-10923; data/mods/gen3/scripts.ts',
			test_name: id, oracle_revision: revision,
		},
		format: 'gen3ou', seed,
		teams: [
			{source: sources[0], normalized: left},
			{source: sources[1], normalized: right},
		],
		source_choices: choices, choices, forced_outcomes: [],
		features: ['choice.move', 'state.canonical', 'hit.accuracy'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
	};
	fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

for (const [level, seed] of [
	[4, [52, 2, 3, 4]], [5, [25, 2, 3, 4]], [6, [142, 2, 3, 4]],
	[7, [135, 2, 3, 4]], [8, [4, 2, 3, 4]], [9, [32, 2, 3, 4]],
	[10, [149, 2, 3, 4]],
]) {
	writeCase({
		id: `magnitude-level-${level}`, seed,
		left: [smeargle(['magnitude'])], right: [blissey(['splash'])],
		choices: [['move 1', 'move 1']],
	});
}

writeCase({
	id: 'magnitude-dig-double', seed: [135, 2, 3, 4],
	left: [smeargle(['splash', 'magnitude'])],
	right: [blissey(['dig', 'softboiled'])],
	choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
});
