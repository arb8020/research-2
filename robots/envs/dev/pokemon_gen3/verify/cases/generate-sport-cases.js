#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const display = new Map([
	['smeargle', 'Smeargle'], ['blissey', 'Blissey'],
	['illuminate', 'Illuminate'], ['naturalcure', 'Natural Cure'],
	['mudsport', 'Mud Sport'], ['watersport', 'Water Sport'],
	['thunderbolt', 'Thunderbolt'], ['surf', 'Surf'], ['ember', 'Ember'],
	['splash', 'Splash'],
]);
const name = id => display.get(id) || `${id[0].toUpperCase()}${id.slice(1)}`;
const pokemon = (species, ability, moves, stats, speedEvs = 0) => ({
	species, level: 100, gender: 'M', ability, item: '', moves, stats,
	status: null, speed_evs: speedEvs,
});
const smeargle = (moves, fast = false) => pokemon(
	'smeargle', 'illuminate', moves,
	fast ? [251, 76, 106, 76, 126, 249] : [251, 76, 106, 76, 126, 186],
	fast ? 252 : 0);
const blissey = moves => pokemon(
	'blissey', 'naturalcure', moves, [651, 56, 56, 186, 306, 146]);

function writeTeam(filename, members) {
	const text = members.map(member =>
		`${name(member.species)} (M)\nAbility: ${name(member.ability)}\n` +
		`Level: 100\n${member.speed_evs ? `EVs: ${member.speed_evs} Spe\n` : ''}` +
		`Hardy Nature\n${member.moves.map(move => `- ${name(move)}`).join('\n')}\n`
	).join('\n');
	fs.writeFileSync(path.join(out, filename), text);
}

function writeCase({id, left, right, choices, features}) {
	const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
	writeTeam(sources[0], left);
	writeTeam(sources[1], right);
	const normalized = members => members.map(({speed_evs, ...member}) => member);
	const fixture = {
		schema: 'pokemon-native-differential-case-v1', id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/mods/gen4/moves.ts:940-953,1482-1495',
			test_name: id, oracle_revision: revision,
		},
		format: 'gen3ou', seed: [71, 2, 3, 4],
		teams: [
			{source: sources[0], normalized: normalized(left)},
			{source: sources[1], normalized: normalized(right)},
		],
		source_choices: choices, choices, forced_outcomes: [],
		features: [
			'choice.move', 'handler.base-power', 'state.canonical', ...features,
		],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
	};
	fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

writeCase({
	id: 'sport-mud-own-match-mismatch',
	left: [smeargle(['mudsport', 'thunderbolt', 'surf'], true)],
	right: [blissey(['splash'])],
	choices: [
		['move 1', 'move 1'], ['move 2', 'move 1'], ['move 3', 'move 1'],
	],
	features: ['move.mudsport', 'volatile.mudsport'],
});

writeCase({
	id: 'sport-water-opposing-match-mismatch',
	left: [smeargle(['watersport', 'splash'], true)],
	right: [smeargle(['ember', 'thunderbolt'])],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	features: ['move.watersport', 'volatile.watersport'],
});

writeCase({
	id: 'sport-mud-duplicate-stack',
	left: [smeargle(['mudsport', 'thunderbolt'], true)],
	right: [smeargle(['mudsport', 'splash'])],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	features: ['move.mudsport', 'volatile.mudsport'],
});

writeCase({
	id: 'sport-mud-switch-cleanup',
	left: [smeargle(['mudsport'], true), blissey(['splash'])],
	right: [smeargle(['thunderbolt'])],
	choices: [['move 1', 'move 1'], ['switch 2', 'move 1']],
	features: ['move.mudsport', 'volatile.mudsport', 'choice.switch'],
});
