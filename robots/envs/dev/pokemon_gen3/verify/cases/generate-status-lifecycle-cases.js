#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');

const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-status-lifecycle-cases.js POKEMON_SHOWDOWN_DIR');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const actual = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);

const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou');
const out = path.resolve(__dirname, 'derived');
const id = 'toxic-switch-in-hazard-order';
const teamTexts = [
	'Skarmory (M)\nAbility: Keen Eye\nLevel: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n- Toxic\n- Spikes\n- Protect\n',
	'Vaporeon (M)\nAbility: Water Absorb\nLevel: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n- Tackle\n\nPersian (M)\nAbility: Limber\nLevel: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n- Scratch\n',
];
const sources = teamTexts.map((text, side) => {
	const source = `${id}-p${side + 1}.txt`;
	const problems = validator.validateTeam(Teams.import(text));
	if (problems) throw new Error(`${source}: ${problems.join('; ')}`);
	fs.writeFileSync(path.join(out, source), text);
	return source;
});
const choices = [
	['move 1', 'move 1'], ['move 2', 'switch 2'], ['move 3', 'switch 1'],
];
const fixture = {
	schema: 'pokemon-native-differential-case-v1', id,
	provenance: {kind: 'showdown-derived', source_file: 'data/conditions.ts; data/mods/gen4/scripts.ts',
		test_name: 'Toxic SwitchIn reset runs after EntryHazard and before residual',
		oracle_revision: revision},
	format: 'gen3ou', seed: [1, 2, 3, 5],
	teams: [
		{source: sources[0], normalized: [{species: 'skarmory', level: 100, gender: 'M',
			nature: 'hardy', ability: 'keeneye', item: '', moves: ['toxic', 'spikes', 'protect'],
			stats: [271, 196, 316, 116, 176, 176], status: null}]},
		{source: sources[1], normalized: [
			{species: 'vaporeon', level: 100, gender: 'M', nature: 'hardy', ability: 'waterabsorb',
				item: '', moves: ['tackle'], stats: [401, 166, 156, 256, 226, 166], status: null},
			{species: 'persian', level: 100, gender: 'M', nature: 'hardy', ability: 'limber',
				item: '', moves: ['scratch'], stats: [271, 176, 156, 166, 166, 266], status: null},
		]},
	],
	source_choices: [choices[0], choices[1], ['move 3', 'switch 2']], choices,
	forced_outcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 32}],
	features: ['choice.move', 'choice.switch', 'condition.nonvolatile-status',
		'condition.side', 'damage.residual', 'handler.entry-hazard', 'handler.status-update',
		'lifecycle.switch-persistence', 'prng.labeled', 'state.canonical', 'status.toxic'],
	boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
	limits: {max_boundaries: 4, max_actions: 6},
};
fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
console.log(`generated ${id}`);
