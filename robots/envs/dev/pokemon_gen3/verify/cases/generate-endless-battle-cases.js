#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const showdownDir = process.argv[2];
if (!showdownDir) {
	throw new Error('usage: generate-endless-battle-cases.js POKEMON_SHOWDOWN_DIR');
}
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const actual = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');
const out = path.resolve(__dirname, 'derived');

const catalog = {
	smeargle: {name: 'Smeargle', ability: 'Own Tempo', stats: [251, 76, 106, 76, 126, 186]},
	alakazam: {name: 'Alakazam', ability: 'Synchronize', stats: [251, 136, 126, 306, 206, 276]},
};
const moveNames = {
	healbell: 'Heal Bell', recycle: 'Recycle', skillswap: 'Skill Swap', splash: 'Splash',
	recover: 'Recover', reflect: 'Reflect', calmmind: 'Calm Mind', lightscreen: 'Light Screen',
};

function member(species, moves, item = '') {
	const entry = catalog[species];
	const text = `${entry.name} (M)${item ? ` @ ${item}` : ''}\n` +
		`Ability: ${entry.ability}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		`${moves.map(move => `- ${moveNames[move]}`).join('\n')}\n`;
	return {text, normalized: {
		species, level: 100, gender: 'M', nature: 'hardy',
		ability: entry.ability.toLowerCase().replace(/ /g, ''),
		item: item.toLowerCase().replace(/ /g, ''), moves, stats: entry.stats,
		status: null,
	}};
}

function team(id, side, members) {
	const source = `${id}-p${side + 1}.txt`;
	const text = members.map(entry => entry.text).join('\n');
	const problems = validator.validateTeam(Teams.import(text));
	if (problems) throw new Error(`${source}: ${problems.join('; ')}`);
	fs.writeFileSync(path.join(out, source), text);
	return {source, normalized: members.map(entry => entry.normalized)};
}

const leftChoices = [];
for (let i = 0; i < 8; i++) leftChoices.push(1);
leftChoices.push(2);
for (let i = 0; i < 8; i++) leftChoices.push(1);
for (let cycle = 0; cycle < 9; cycle++) {
	leftChoices.push(2);
	for (let i = 0; i < 8; i++) leftChoices.push(1);
}
leftChoices.push(2, 1, 3);
if (leftChoices.length !== 101) throw new Error('unexpected EBC sequence length');
const rightChoices = leftChoices.map((_, index) =>
	index < 32 ? 1 : index < 64 ? 2 : index < 96 ? 3 : 4);
const choices = leftChoices.map((slot, index) =>
	[`move ${slot}`, `move ${rightChoices[index]}`]);
const id = 'endless-battle-recycle-skill-swap-winner';
const fixture = {
	schema: 'pokemon-native-differential-case-v1', id,
	provenance: {
		kind: 'showdown-derived',
		source_file: 'sim/battle.ts; sim/pokemon.ts; data/rulesets.ts; test/sim/rulesets/endlessbattleclause.js',
		test_name: 'legal Gen 3 recycled restorative plus opposing Skill Swap staleness activates EBC after turn 100',
		oracle_revision: revision,
	},
	format: 'gen3ou', seed: [601, 1001, 3, 6],
	teams: [
		team(id, 0, [member('smeargle', ['healbell', 'recycle', 'skillswap', 'splash'], 'Leppa Berry')]),
		team(id, 1, [member('alakazam', ['recover', 'reflect', 'calmmind', 'lightscreen'])]),
	],
	source_choices: choices, choices, forced_outcomes: [],
	features: ['format.endless-battle-clause', 'item.recycle', 'state.canonical', 'lifecycle.terminal'],
	boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng', 'terminal'],
	limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
};
fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
console.log(`generated ${id}: ${choices.length} turns`);
